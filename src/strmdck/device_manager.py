from typing import Union

import hid

from .device import DeckDevice
from .devices.ulanzi_d200 import UlanziD200Device

DEVICE_MAP = {
    (UlanziD200Device.USB_VENDOR_ID, UlanziD200Device.USB_PRODUCT_ID): UlanziD200Device,
}


def auto_connect() -> Union[None, DeckDevice]:
    for device_dict in hid.enumerate():
        tuple_id = (device_dict['vendor_id'], device_dict['product_id'])
        if tuple_id in DEVICE_MAP:
            try:
                device = hid.device()
                device.open(tuple_id[0], tuple_id[1])
                device.set_nonblocking(True)
            except Exception as e:
                print(e)
                continue

            device_class = DEVICE_MAP[tuple_id]
            return device_class(device)

    return None
