# Final version with archive unpacking, logging, preview support, and docstrings

import os
import sys
import shutil
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path
import re
from transliterate import translit
import zipfile
import tarfile

def print_usage():
    """
    Prints usage instructions for the script.

    No arguments.
    No return value.
    """
    print("Usage: script.py <source_dir> <target_dir> [--preview] [--fallback-to-mtime]")
    print("Moves image files based on EXIF date into <target>/YYYY/MM/")
    print("Conflicts resolved by hash. Identical files skipped.")

def transliterate_ru_to_en(name):
    """
    Transliterates Russian (Cyrillic) text to Latin using the `transliterate` library.
    """
    return translit(name, 'ru', reversed=True)

def sha256sum_file(path):
    """
    Calculates SHA256 hash of a file.
    """
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()

def get_exif_date(file_path, tag):
    """
    Extracts EXIF datetime from a file using exiftool.
    """
    result = subprocess.run(['exiftool', '-d', '%Y-%m-%d %H:%M:%S', f'-{tag}', '-s3', str(file_path)],
                            capture_output=True, text=True)
    return result.stdout.strip()

def update_timestamps(file_path, date_str, ext):
    """
    Updates file timestamps to match EXIF date.
    """
    if ext in ['jpg', 'jpeg', 'png', 'heic', 'heif', 'webp']:
        subprocess.run(['exiftool', '-overwrite_original',
                        f'-FileModifyDate<DateTimeOriginal',
                        f'-FileCreateDate<DateTimeOriginal',
                        str(file_path)], capture_output=True)
    elif ext in ['mp4', 'mov', 'mpg', 'avi', 'mts', 'm2ts', '3gp', '3g2', 'wmv']:
        subprocess.run(['exiftool', '-overwrite_original',
                        f'-FileModifyDate<CreateDate',
                        f'-FileCreateDate<CreateDate',
                        str(file_path)], capture_output=True)
    os.utime(file_path, (datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S').timestamp(),) * 2)

def log_move(global_log_path, month_log_path, src, dst):
    """
    Logs a file move or unpacking action to both a global and a monthly log file.
    """
    entry = f"{datetime.now().isoformat()} | {src} -> {dst}\n"
    with open(global_log_path, 'a') as g:
        g.write(entry)
    with open(month_log_path, 'a') as m:
        m.write(entry)

def unpack_archives_in_place(folder, log_path, preview):
    """
    Scans and unpacks supported archives in-place inside the source folder.
    """
    for archive in folder.rglob("*"):
        if not archive.is_file():
            continue
        ext = archive.suffix.lower()
        try:
            if ext == ".zip":
                with zipfile.ZipFile(archive, 'r') as z:
                    extract_to = archive.parent
                    if not preview:
                        z.extractall(path=extract_to)
                        log_move(log_path, log_path, str(archive), f"Unpacked to {extract_to}")
                        print(f"[~] Unpacked ZIP: {archive}")
            elif ext in [".tar", ".gz", ".tgz", ".bz2", ".xz"]:
                with tarfile.open(archive, 'r:*') as tar:
                    if not preview:
                        tar.extractall(path=archive.parent)
                        log_move(log_path, log_path, str(archive), f"Unpacked to {archive.parent}")
                        print(f"[~] Unpacked TAR: {archive}")
        except Exception as e:
            print(f"[!] Failed to unpack {archive}: {e}")

def main():
    if len(sys.argv) < 3:
        print_usage()
        sys.exit(1)

    source = Path(sys.argv[1]).resolve()
    target = Path(sys.argv[2]).resolve()
    preview = '--preview' in sys.argv
    fallback_to_mtime = '--fallback-to-mtime' in sys.argv

    if not source.is_dir():
        print(f"Source directory does not exist: {source}")
        sys.exit(2)

    print(f"Source: {source}")
    print(f"Target: {target}")
    if preview:
        print("[PREVIEW MODE — No files will be moved]")

    target.mkdir(parents=True, exist_ok=True)
    global_log_file = target / "media_organizer.log"

    # Unpack archives before processing
    unpack_archives_in_place(source, global_log_file, preview)

    extensions = ['.jpg', '.jpeg', '.png', '.mp4', '.mov', '.mpg', '.avi',
                  '.heic', '.heif', '.3gp', '.webp', '.mts', '.m2ts', '.3g2', '.wmv']

    for src_file in source.rglob('*'):
        if not src_file.is_file() or src_file.suffix.lower() not in extensions:
            continue

        ext = src_file.suffix.lower()[1:]
        base_name = src_file.name
        thm_file = src_file.with_suffix('.THM')
        json_file = src_file.with_suffix(src_file.suffix + '.json')

        tag = 'DateTimeOriginal' if ext in ['jpg', 'jpeg', 'png', 'heic', 'heif', 'webp'] else 'CreateDate'
        exif_date = get_exif_date(src_file, tag)

        if thm_file.exists():
            thm_date = get_exif_date(thm_file, 'DateTimeOriginal')
            if thm_date and not re.match(r'0000[-:]00[-:]00 00:00:00', thm_date):
                exif_date = thm_date
                print(f"[~] Using .THM metadata: {thm_file} → {exif_date}")

        if not exif_date or re.match(r'0000[-:]00[-:]00 00:00:00', exif_date):
            if fallback_to_mtime:
                exif_date = datetime.fromtimestamp(src_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                print(f"[~] Fallback to file timestamp: {src_file} → {exif_date}")
            else:
                print(f"[!] Skipping: {src_file} (no valid date)")
                continue

        year, month = exif_date.split('-')[:2]
        dest_dir = target / year / month
        dest_dir.mkdir(parents=True, exist_ok=True)
        month_log_file = dest_dir / "media_organizer.log"

        tgt_file = dest_dir / base_name
        if re.search(r'[А-Яа-я]', base_name):
            tgt_file = dest_dir / transliterate_ru_to_en(base_name)
            thm_file = thm_file.with_name(transliterate_ru_to_en(thm_file.name))

        if tgt_file.exists():
            src_hash = sha256sum_file(src_file)
            tgt_hash = sha256sum_file(tgt_file)
            if src_hash == tgt_hash:
                print(f"[=] Identical: {base_name} (skipped)")
                continue
            else:
                suffix = datetime.now().strftime('%Y%m%d_%H%M%S')
                new_name = f"{src_file.stem}_copy_{suffix}{src_file.suffix}"
                tgt_file = dest_dir / new_name
                print(f"[!] Conflict: {base_name} → {new_name}")

        if preview:
            print(f"[+] Would move: {base_name} → {year}/{month}/{tgt_file.name}")
            if thm_file.exists():
                print(f"[+] Would move thumbnail: {thm_file.name} → {year}/{month}/{thm_file.name}")
        else:
            shutil.move(src_file, tgt_file)
            log_move(global_log_file, month_log_file, str(src_file), str(tgt_file))
            print(f"[+] Moved: {base_name} → {year}/{month}/{tgt_file.name}")
            if thm_file.exists():
                shutil.move(thm_file, dest_dir)
                log_move(global_log_file, month_log_file, str(thm_file), str(dest_dir / thm_file.name))
                print(f"[+] Moved thumbnail: {thm_file.name} → {year}/{month}/{thm_file.name}")

if __name__ == "__main__":
    main()
