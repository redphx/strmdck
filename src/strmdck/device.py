from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import List, Union


class DeckCommand(Enum):
    BUTTON = 0


@dataclass
class DeckIncomingCommand:
    command: DeckCommand
    data: any


@dataclass
class ButtonAction:
    index: int
    pressed: bool
    state: any


class DeckDevice(ABC):
    POLLING_RATE = 0.05
    ICON_WIDTH = 0
    ICON_HEIGHT = 0

    def __init__(self, hid_device):
        self._hid_device = hid_device
        self._lock = asyncio.Lock()

        self._brightness = 0
        self._small_window_data = None
        self._label_style = None

    def close(self):
        try:
            self._hid_device.close()
        except Exception:
            pass
        finally:
            self._hid_device = None

    @abstractmethod
    def keep_alive(self):
        pass

    @abstractmethod
    def set_brightness(self, brightness: int, force=False):
        pass

    @abstractmethod
    def set_label_style(self, label_style, force=False):
        pass

    @abstractmethod
    def set_small_window_data(self, data, force=False):
        pass

    @abstractmethod
    def set_buttons(self):
        pass

    @abstractmethod
    def _parse_input(self, inp):
        return None

    @abstractmethod
    def set_small_window_mode(self, mode):
        pass

    @abstractmethod
    def restore_small_window(self):
        pass

    async def read_packet(self, length=1024):
        while True:
            if not self._hid_device:
                break
            inp = self._hid_device.read(length)
            if not inp:
                await asyncio.sleep(DeckDevice.POLLING_RATE)
                continue

            command = self._parse_input(inp)
            yield command

            await asyncio.sleep(DeckDevice.POLLING_RATE)

    def _write_packet(self, packet: Union[str, List[str]]):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._write_packet_async(packet))
        except Exception as e:
            print('_write_packet', e)

    async def _write_packet_async(self, packet: Union[str, List[str]]):
        async with self._lock:
            if not self._hid_device:
                return

            try:
                if isinstance(packet, list):
                    for pkt in packet:
                        self._hid_device.write(pkt)
                else:
                    self._hid_device.write(packet)
            except Exception:
                pass
