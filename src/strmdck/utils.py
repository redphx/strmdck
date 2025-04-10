import os
import random
import string
import zipfile


def random_string(length: int) -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def compress_folder(folder_path, output_zip, compress_level=0):
    method = zipfile.ZIP_STORED if compress_level == 0 else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(output_zip, 'w', method, compresslevel=compress_level) as zipf:
        # Write dummy.txt at the beginning of the zip file
        dummy_path = os.path.join(folder_path, 'dummy.txt')
        if (os.path.exists(dummy_path)):
            zipf.write(dummy_path, os.path.relpath(dummy_path, folder_path))

        for root, _, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                if file_path == dummy_path:
                    # Don't write dummy file again
                    continue

                arcname = os.path.relpath(file_path, folder_path)  # Preserve folder structure
                zipf.write(file_path, arcname)
