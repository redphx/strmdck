from __future__ import annotations

import binascii
import json
import os
import shutil
import time
from datetime import datetime
from enum import Enum
from typing import Dict
from zoneinfo import ZoneInfo

from construct import (
    Adapter,
    Byte,
    Bytes,
    BytesInteger,
    ByteSwapped,
    Const,
    CString,
    ExprAdapter,
    GreedyBytes,
    Int32ub,
    Padded,
    Struct,
    Switch,
    this,
)
from deepdiff import DeepDiff
from dotenv import load_dotenv

from ..device import ButtonAction, DeckDevice
from ..utils import compress_folder, random_string

load_dotenv()
timezone = ZoneInfo(os.getenv('TIMEZONE', 'America/New_York'))


class SmallWindowMode(Enum):
    STATS = 0
    CLOCK = 1
    BACKGROUND = 2


class CommandProtocol(Enum):
    OUT_SET_BUTTONS = 0x0001
    OUT_PARTIALLY_UPDATE_BUTTONS = 0x000d

    OUT_SET_SMALL_WINDOW_DATA = 0x0006
    OUT_SET_BRIGHTNESS = 0x000a
    OUT_SET_LABEL_STYLE = 0x000b

    IN_BUTTON = 0x0101
    IN_DEVICE_INFO = 0x0303


class LengthAdapter(Adapter):
    def _encode(self, obj, context, path):
        return obj if obj is not None else len(context.data)

    def _decode(self, obj, context, path):
        return obj


PacketStruct = Struct(
    Const(b'\x7c\x7c'),
    'command_protocol' / BytesInteger(2),
    'length' / LengthAdapter(ByteSwapped(Int32ub)),
    'data' / Padded(1024 - 8, GreedyBytes),
)


ButtonPressedStruct = Struct(
    'state' / Byte,
    'index' / Byte,
    Const(b'\x01'),
    'pressed' / ExprAdapter(Byte, lambda obj, ctx: obj == 0x1, lambda obj, ctx: 0x1 if obj else 0x0),
)

IncomingStruct = Struct(
    Bytes(2),  # b'\x7c\x7c'
    'command_protocol' / BytesInteger(2),
    'length' / ByteSwapped(Int32ub),
    'data' / Switch(this.command_protocol, {0x0101: ButtonPressedStruct, 0x0303: CString('ascii')}),
)


class UlanziD200Device(DeckDevice):
    USB_VENDOR_ID = 0x2207
    USB_PRODUCT_ID = 0x0019

    BUTTON_COUNT = 13
    BUTTON_ROWS = 3
    BUTTON_COLS = 5

    ICON_WIDTH = 196
    ICON_HEIGHT = 196

    DECK_NAME = 'Ulanzi Stream Controller D200'

    def __init__(self, hid_device):
        super().__init__(hid_device)
        self._small_window_mode = SmallWindowMode.CLOCK

    def keep_alive(self):
        self.set_small_window_data({})

    def set_brightness(self, brightness: int, force=False):
        if not force and brightness == self._brightness:
            return

        self._brightness = brightness
        packet = PacketStruct.build(dict(
            command_protocol=CommandProtocol.OUT_SET_BRIGHTNESS.value,
            length=None,
            data=str(brightness).encode('utf-8'),
        ))

        self._write_packet(packet)

    def set_label_style(self, label_style: Dict, force=False):
        if not force and not DeepDiff(self._label_style, label_style):
            return False

        label_style.setdefault('align', 'bottom')
        label_style.setdefault('color', 'FFFFFF')
        label_style.setdefault('font_name', 'Roboto')
        label_style.setdefault('show_title', True)
        label_style.setdefault('size', 10)
        label_style.setdefault('weight', 80)
        self._label_style = label_style

        style = {
            'Align': label_style['align'],
            'Color': int(label_style['color'], 16),
            'FontName': label_style['font_name'],
            'ShowTitle': bool(label_style['show_title']),
            'Size': label_style['size'],
            'Weight': label_style['weight'],
        }

        packet = PacketStruct.build(dict(
            command_protocol=CommandProtocol.OUT_SET_LABEL_STYLE.value,
            length=None,
            data=bytearray(json.dumps(style).encode('utf-8')),
        ))

        self._write_packet(packet)
        print('set_label_style')

    def set_small_window_data(self, data: Dict, force=False):
        if not force and not DeepDiff(self._small_window_data, data):
            return False

        data.setdefault('time', datetime.now(timezone).strftime('%H:%M:%S'))
        data.setdefault('mode', self._small_window_mode)
        data.setdefault('cpu', 0)
        data.setdefault('mem', 0)
        data.setdefault('gpu', 0)

        self._small_window_data = data

        # "1|9|64|16:23:04|0"  cpu: "9"  mem: "64"  time: "16:23:04"  GPU: "0"
        data = f'{data["mode"].value}|{data["cpu"]}|{data["mem"]}|{data["time"]}|{data["gpu"]}'

        packet = PacketStruct.build(dict(
            command_protocol=CommandProtocol.OUT_SET_SMALL_WINDOW_DATA.value,
            length=None,
            data=data.encode('utf-8'),
        ))

        self._write_packet(packet)

    def set_buttons(self, buttons: Dict[int, Dict], *, update_only=False):
        self._prepare_zip(buttons)
        chunk_size = 1024

        data = b''
        # with open('bk/12345678-bug.zip', 'rb') as fp:
        with open(os.path.join('.build', 'build.zip'), 'rb') as fp:
            data += fp.read()

        file_size = len(data)

        command = CommandProtocol.OUT_PARTIALLY_UPDATE_BUTTONS if update_only else CommandProtocol.OUT_SET_BUTTONS
        chunk = data[:chunk_size - 8]
        packet = PacketStruct.build(dict(
            command_protocol=command.value,
            length=file_size,
            data=chunk.ljust(chunk_size - 8, b'\x00'),
        ))

        packets = [packet]

        for i in range(chunk_size - 8, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            chunk = chunk.ljust(chunk_size, b'\x00')
            packets.append(chunk)

        print('send_zip', file_size)
        self._write_packet(packets)

    def _parse_input(self, inp):
        try:
            parsed = IncomingStruct.parse(bytes(inp))
        except Exception as e:
            print('_parse_input', e)
            print(binascii.hexlify(bytes(inp)))
            return None

        data = parsed['data']
        if not data:
            return None

        command_protocol = parsed['command_protocol']
        if command_protocol == CommandProtocol.IN_DEVICE_INFO.value:
            print('_parse_input', data)
        elif command_protocol == CommandProtocol.IN_BUTTON.value:
            self._last_action_time = time.time()

            return ButtonAction(index=data['index'], pressed=data['pressed'], state=data['state'])

    def set_small_window_mode(self, mode):
        try:
            self._small_window_mode = SmallWindowMode(mode)
        except Exception:
            self._small_window_mode = SmallWindowMode.CLOCK

    def restore_small_window(self):
        self.set_small_window_data({
            'mode': self._small_window_mode,
        })

    def _prepare_zip(self, buttons: Dict) -> bool:
        manifest = {}

        shutil.rmtree('.build', ignore_errors=True)
        os.makedirs(os.path.join('.build', 'page', 'icons'), exist_ok=True)

        for button_index, button in buttons.items():
            button_index = int(button_index)
            row = button_index // self.BUTTON_COLS
            index = button_index % self.BUTTON_COLS

            button_data = {
                'State': 0,
                'ViewParam': [{}],
            }

            if button:
                if 'name' in button:
                    button_data['ViewParam'][0]['Text'] = button['name']

                if 'icon' in button:
                    # Copy icon
                    icon_name = button['icon']
                    icon_path = os.path.join('.cache', 'icons', '_generated', icon_name)
                    shutil.copyfile(icon_path, os.path.join('.build', 'page', 'icons', icon_name))

                    button_data['ViewParam'][0]['Icon'] = f'icons/{icon_name}'

            manifest[f'{index}_{row}'] = button_data

        page_path = os.path.join('.build', 'page')
        with open(os.path.join(page_path, 'manifest.json'), 'w') as fp:
            json.dump(manifest, fp, sort_keys=True, separators=(',', ':'), indent=2)

        # Chunks start with these bytes cause problems
        invalid_bytes = [
            b'\x00',
            # b'\x01',
            b'\x7c',
        ]

        dummy_str = ''
        dummy_retries = 0
        dummy_path = os.path.join(page_path, 'dummy.txt')

        while True:
            # Write a dummy file with random string to modify the zip
            if dummy_retries > 0:
                with open(dummy_path, 'w') as fp:
                    print('Generating dummy string...')
                    dummy_str += random_string(8 * dummy_retries)
                    fp.write(dummy_str)

            # Create ZIP file
            compress_folder(page_path, '.build.zip', 1)
            file_size = os.path.getsize('.build.zip')

            # There is a bug with the deck when byte value at 1016, 1016 + 1024... is one of invalid_bytes
            # Check to avoid that
            valid = True
            with open('.build.zip', 'rb') as fp:
                for i in range(1016, file_size, 1024):
                    fp.seek(i)
                    byte_at = fp.read(1)
                    if byte_at in invalid_bytes:
                        valid = False
                        break

            if valid:
                break

            dummy_retries += 1
            time.sleep(0.05)

        shutil.move('.build.zip', os.path.join('.build', 'build.zip'))
        return True
