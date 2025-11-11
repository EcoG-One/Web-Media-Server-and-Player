import os
import ffmpeg
from ffcuesplitter.cuesplitter import FFCueSplitter
from ffcuesplitter.user_service import FileSystemOperations


def cue_spliter(cue_file: str, output_dir: str = '.', dry_run: bool = False):
    splitter = FFCueSplitter(cue_file, output_dir, dry=dry_run)
    if dry_run:
        splitter.dry_run_mode()
    else:
        overwrite = splitter.check_for_overwriting()
        if not overwrite:
            splitter.work_on_temporary_directory()


def ape_to_flac_converter(convert_dir: str):
# convert_dir = "/path/to/folder/tobeconverted"
    for root, dirs, files in os.walk(convert_dir):
        for name in files:
            if name.endswith(".ape"):
                # filepath+name
                file = root+"/" + name
               # file = file.replace("\\", "/")
                file =  os.path.normpath(file)
                output = file.replace(".ape", ".flac")
                try:
                    (ffmpeg .input(file) .output(output) .run())
                except FileNotFoundError as e:
                    print("File not found. ", e)
                except Exception as e:
                    print("Error: ", e)
            else:
                pass

if __name__ == "__main__":
    # Example usage:
    cue_file_path = "example.cue"
    output_directory = "output"
    dry_run_mode = True

    cue_spliter(cue_file_path, output_directory, dry_run_mode)

    convert_directory = "to_be_converted"
    ape_to_flac_converter(convert_directory)