import os
import sys
import shutil
import hashlib
import subprocess
from datetime import datetime
import getpass
from pathlib import Path
import re
from transliterate import translit
import zipfile
import tarfile
import rarfile
import json
from concurrent.futures import ThreadPoolExecutor
import threading

# Media file extensions
MEDIA_EXTENSIONS = {
    'image': ['jpg', 'jpeg', 'png', 'heic', 'heif', 'webp', 'dng'],
    'video': ['mp4', 'mov', 'mpg', 'avi', 'mts', 'm2ts', '3gp', '3g2', 'wmv']
}

# Archive types
ARCHIVE_TYPES = {
    '.zip': zipfile.ZipFile,
    '.tar': tarfile.TarFile,
    '.gz': tarfile.TarFile,
    '.tgz': tarfile.TarFile,
    '.bz2': tarfile.TarFile,
    '.xz': tarfile.TarFile,
    '.rar': rarfile.RarFile
}

# Thread-safe logging lock and log backup tracker
log_lock = threading.Lock()
backed_up_logs = set()


def print_usage():
    """Prints usage instructions."""
    print("Organizes media files based on EXIF or extracted metadata into <target>/YYYY/MM/")
    print("Duplicates are handled by comparing hashes.")
    print('')
    print("Usage: script.py <source_dir> <target_dir> [OPTIONS]")
    print("Options:")
    print("[--preview] - Preview mode, no files will be moved") 
    print("[--fallback-to-mtime] - Use file's mtime if no EXIF date found")
    print("[--remove-duplicates] - Remove duplicate files instead of skipping")
    print("[--extract-archives] - Extract archives before processing. Supports: .zip, .tar, .gz, .tgz, .bz2, .xz, .rar")
    print("[--password <password>] - Password for encrypted archives")
    print("[--threads <num>] - Number of parallel threads (default: 2 x CPU cores)")

def transliterate_ru_to_en(name):
    """Transliterates Cyrillic names to Latin characters."""
    return translit(name, 'ru', reversed=True)

def sha256sum_file(path, chunk_size=8192):
    """Calculates SHA256 hash of a file."""
    hash_sha256 = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()

def get_exif_date(file_path, tag):
    """Extracts EXIF datetime using exiftool."""
    result = subprocess.run(
        ['exiftool', '-d', '%Y-%m-%d %H:%M:%S', f'-{tag}', '-s3', str(file_path)],
        capture_output=True, text=True
    )
    return result.stdout.strip()

def parse_json_metadata(json_file):
    """
    Parses JSON metadata to retrieve the photo taken time from the 'timestamp'.
    Returns formatted date string or None if not found.
    """
    try:
        with open(json_file, 'r') as jf:
            data = json.load(jf)
            # Extract the timestamp value
            timestamp_value = data.get('photoTakenTime', {}).get('timestamp')
            if timestamp_value is not None:
                # Convert timestamp to datetime object
                dt_object = datetime.fromtimestamp(int(timestamp_value))
                # Return formatted date-time string
                return dt_object.strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        print(f"Error parsing JSON: {e}")
    return None

def extract_date_from_filename(filename):
    """Extracts a date from the filename."""
    # Find possible date in the format YYYYMMDD_HHMMSS
    matches = re.search(r'(\d{8}_\d{6})', filename)
    if matches:
        date_part = matches.group(0)
        try:
            # Convert the found date and time
            dt_obj = datetime.strptime(date_part, "%Y%m%d_%H%M%S")
            return dt_obj.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None

def update_timestamps(file_path, date_str, ext):
    """Updates file creation/modification times according to EXIF data."""
    if ext in MEDIA_EXTENSIONS['image']:
        cmd = [
            'exiftool', '-overwrite_original',
            f'-FileModifyDate<DateTimeOriginal',
            f'-FileCreateDate<DateTimeOriginal',
            str(file_path),
        ]
    elif ext in MEDIA_EXTENSIONS['video']:
        cmd = [
            'exiftool', '-overwrite_original',
            f'-FileModifyDate<CreateDate',
            f'-FileCreateDate<CreateDate',
            str(file_path),
        ]
    if ext in MEDIA_EXTENSIONS['image'] + MEDIA_EXTENSIONS['video']:
        subprocess.run(cmd, capture_output=True)
        print(f"[+] Updated EXIF timestamps for {file_path}")
    os.utime(file_path, (datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S').timestamp(),) * 2)
    print(f"[+] Updated filesystem timestamps for {file_path}")

def correct_timestamps(file_path, date_str, ext):
    """Corrects EXIF timestamps using exiftool and updates filesystem timestamps."""
    # Get current file modification date
    current_date_str = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[~] Current timestamps for {file_path}: {current_date_str}, EXIF date: {date_str}")
    if date_str != current_date_str:
        update_timestamps(file_path, date_str, ext)
    else:
        print(f"[=] Timestamps already correct for {file_path}")

def log_move(global_log_path, month_log_path, src, dst):
    """Logs file movement details to both global and monthly logs."""
    entry = f"{datetime.now().isoformat()} | {src} -> {dst}\n"
    with log_lock:
        with open(global_log_path, 'a') as g:
            g.write(entry)
        with open(month_log_path, 'a') as m:
            m.write(entry)

def extract_archive_with_password(archive_path, output_folder, pwd=None):
    """Extracts an archive using 7z tool, controlling interactive behavior."""
    try:
        if pwd is None:
            # Allows to bypass interactive password prompt if archive is password protected
            cmd = ["7z", "x", str(archive_path), f"-o{output_folder}", "-p", "-y"]
        else:
            cmd = ["7z", "x", str(archive_path), f"-o{output_folder}", f"-p{pwd}", "-y"]

        # Execute the command without special manipulation of stdio
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        stdout, stderr = proc.communicate()  # Wait for completion
        
        if proc.returncode != 0 and "Wrong password" in stderr:
            if pwd is None:
                print(f"[!] Archive {archive_path} requires a password.")
            else:
                print(f"[!] Wrong password provided for {archive_path}, skipping.")
            return False
        return True
    except Exception as e:
        print(f"[!] Unexpected error during extraction: {e}")
        return False

def extract_archive(archive_path, output_folder, pwd=None):
    """Extracts an archive using 7z tool, prompting for password if necessary."""
    try:
        # Start extraction without password
        if not extract_archive_with_password(archive_path, output_folder):
            # If password is explicitly needed, prompt user to enter it
            if pwd is None:
                pwd = getpass.getpass(f"Enter password for {archive_path}: ")
            else:
                print(f"[!] Retrying with provided password for {archive_path}")
            return extract_archive_with_password(archive_path, output_folder, pwd)
        return True
    except Exception as e:
        print(f"[!] Extraction failed: {e}")
        return False

def resolve_conflict(file_path, dest_dir):
    """Resolves naming conflicts by creating a separate folder for conflicting files."""
    conflict_dir = dest_dir / "conflicts"
    conflict_dir.mkdir(exist_ok=True)
    return conflict_dir / file_path.name

def backup_existing_log(log_path):
    """Backs up existing log file by appending a numeric index."""
    i = 1
    while True:
        backup_path = log_path.with_suffix(f'{log_path.suffix}.{i}')
        if not backup_path.exists():
            shutil.copy(log_path, backup_path)
            break
        i += 1

def extract_archives_in_place(folder, log_path, preview, pwd=None):
    """Recursively scans and extracts archives in place."""
    for archive in folder.rglob("*"):
        if not archive.is_file():
            continue
        ext = archive.suffix.lower()
        try:
            extractor = ARCHIVE_TYPES.get(ext)
            if extractor:
                if not preview:
                    print(f"[~] Unpacking {archive}...")
                    if extract_archive(archive, archive.parent, pwd):
                        log_move(log_path, log_path, str(archive), f"Unpacked to {archive.parent}")
                        archive.unlink()  # Remove archive file
                        print(f"[x] Removed archive file: {archive}")
                else:
                    print(f"[~] Would unpack {archive}")
        except Exception as e:
            print(f"[!] Error extracting {archive}: {e}")

def remove_empty_directories(start_path):
    """
    Recursively removes empty directories starting from the specified start_path.
    """
    for current_dir, dirs, files in os.walk(start_path, topdown=False):
        # If directory is empty, remove it
        if not dirs and not files:
            try:
                os.rmdir(current_dir)
                print(f"[x] Removed: {current_dir} (directory is empty)")
            except OSError as e:
                print(f"[!] Error removing directory {current_dir}: {e}")


def process_file(src_file, target_root, preview=False, fallback_to_mtime=False, remove_duplicates=False):
    """Processes individual media files, handling metadata extraction and duplicate resolution."""

    global global_log_file

    ext = src_file.suffix.lower()[1:]
    base_name = src_file.name
    json_file = Path(str(src_file) + '.json')
    thm_file = src_file.with_suffix('.THM')

    try:
        # Determine the best possible date/time
        exif_date = None
        methods_used = []

        # Try getting EXIF data first
        tag = 'DateTimeOriginal' if ext in MEDIA_EXTENSIONS['image'] else 'CreateDate'
        exif_date = get_exif_date(src_file, tag)

        # Try extracting date from filename
        filename_date = extract_date_from_filename(base_name)

        if exif_date and not re.match(r'0000[-:]00[-:]00 00:00:00', exif_date):
            methods_used.append("EXIF")
        # Check for associated JSON metadata
        elif json_file.exists():
            print(f"[!] No date found for {src_file}, falling back to JSON file")
            json_date = parse_json_metadata(json_file)
            if json_date:
                exif_date = json_date
                methods_used.append("JSON")
                print(f"[+] Using JSON date for {src_file}: {exif_date}")
        # Check for associated thumbnail metadata
        elif thm_file.exists():
            print(f"[!] No date found for {src_file}, falling back to thumbnail file")
            thm_date = get_exif_date(thm_file, 'CreateDate')
            if thm_date:
                exif_date = thm_date
                methods_used.append("THM")
                print(f"[+] Using THM date for {src_file}: {exif_date}")
        # Check filename pattern matching
        elif filename_date:
            print(f"[!] No date found for {src_file}, falling back to filename date")
            exif_date = filename_date
            methods_used.append("Filename")
            print(f"[+] Using filename date for {src_file}: {exif_date}")
        # Fall back to file's last modified time if needed
        else:
            if fallback_to_mtime:
                print(f"[!] No date found for {src_file}, falling back to mtime")
                exif_date = datetime.fromtimestamp(src_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                methods_used.append("FALLBACK (MTIME)")
            else:
                print(f"[!] Skipping: {src_file} (no valid date)")
                return

        if not exif_date or not re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', exif_date):
            print(f"[!] Invalid or missing date for {src_file}, skipping.")
            return

        # Create destination paths
        year, month = exif_date.split('-')[:2]
        dest_dir = target_root / year / month
        dest_dir.mkdir(parents=True, exist_ok=True)
        month_log_file = dest_dir / "media_organizer.log"
        # Target file path setup
        tgt_file = dest_dir / base_name
        if re.search(r'[А-Яа-я]', base_name):
            tgt_file = dest_dir / transliterate_ru_to_en(base_name)

        # Backup log once per month safely
        month_key = f"{year}-{month}"
        with log_lock:
            if month_key not in backed_up_logs and month_log_file.exists():
                backup_existing_log(month_log_file)
                month_log_file.unlink()
                backed_up_logs.add(month_key)
        # Resolve potential duplicate file issues
        if tgt_file.exists():
            if src_file.stat().st_size != tgt_file.stat().st_size:
                # Different sizes, handle it by renaming
                tgt_file = resolve_conflict(src_file, dest_dir)
            else:
                # Same size, check hash
                src_hash = sha256sum_file(src_file)
                tgt_hash = sha256sum_file(tgt_file)
                if src_hash == tgt_hash:
                    if remove_duplicates:
                        src_file.unlink()
                        print(f"[=] Identical: {base_name} (removed)")
                    else:
                        print(f"[=] Identical: {base_name} (skipped)")
                    return
                else:
                    # Hash mismatch, create a copy with unique name
                    suffix = datetime.now().strftime('%Y%m%d_%H%M%S')
                    new_name = f"{src_file.stem}_copy_{suffix}{src_file.suffix}"
                    tgt_file = dest_dir / new_name
                    print(f"[!] Conflict: {base_name} → {new_name}")

        if preview:
            print(f"[+] Would move: {base_name} → {year}/{month}/{tgt_file.name}")
            if thm_file.exists():
                print(f"[+] Would move thumbnail: {thm_file.name} → {year}/{month}/{thm_file.name}")
            if json_file.exists():
                print(f"[+] Would move JSON: {json_file.name} → {year}/{month}/{json_file.name}")
        else:
            if src_file.exists():
                shutil.move(src_file, tgt_file)
                correct_timestamps(tgt_file, exif_date, ext)
                log_move(global_log_file, month_log_file, str(src_file), str(tgt_file))
                print(f"[+] Moved: {base_name} → {year}/{month}/{tgt_file.name}")
            if thm_file.exists():
                shutil.move(thm_file, dest_dir)
                correct_timestamps(dest_dir / thm_file.name, exif_date, thm_file.suffix.lower()[1:])
                log_move(global_log_file, month_log_file, str(thm_file), str(dest_dir / thm_file.name))
                print(f"[+] Moved thumbnail: {thm_file.name} → {year}/{month}/{thm_file.name}")
            if json_file.exists():
                shutil.move(json_file, dest_dir)
                correct_timestamps(dest_dir / json_file.name, exif_date, json_file.suffix.lower()[1:])
                log_move(global_log_file, month_log_file, str(json_file), str(dest_dir / json_file.name))
                print(f"[+] Moved JSON: {json_file.name} → {year}/{month}/{json_file.name}")
    except Exception as e:
        print(f"[!] Error processing file {src_file}: {e}")


def main():
    if len(sys.argv) < 3:
        print_usage()
        sys.exit(1)

    source = Path(sys.argv[1]).resolve()
    target = Path(sys.argv[2]).resolve()
    preview = '--preview' in sys.argv
    fallback_to_mtime = '--fallback-to-mtime' in sys.argv
    remove_duplicates = '--remove-duplicates' in sys.argv
    extract_archives = '--extract-archives' in sys.argv


    if '--password' in sys.argv:
        pwd_index = sys.argv.index('--password') + 1
        if pwd_index < len(sys.argv):
            pwd = sys.argv[pwd_index]
        else:
            print("Error: No password provided after --password")
            sys.exit(1)
    else:
        pwd = None
    
    # Determine number of threads
    threads = os.cpu_count() * 2
    if '--threads' in sys.argv:
        try:
            t_index = sys.argv.index('--threads') + 1
            if t_index < len(sys.argv):
                threads = int(sys.argv[t_index])
                if threads < 1:
                    raise ValueError
            else:
                raise ValueError
        except ValueError:
            print("Error: Invalid number of threads specified after --threads")
            sys.exit(1)

    if not source.is_dir():
        print(f"Source directory does not exist: {source}")
        sys.exit(2)

    print(f"Source: {source}")
    print(f"Target: {target}")
    print(f"Threads: {threads}")
    if preview:
        print("[PREVIEW MODE — No files will be moved]")

    target.mkdir(parents=True, exist_ok=True)

    # Set up global log file
    global global_log_file
    global_log_file = target / "media_organizer.log"
    if global_log_file.exists():
        backup_existing_log(global_log_file)
        global_log_file.unlink()

    # Extract archives before scanning files
    if extract_archives:
        extract_archives_in_place(source, global_log_file, preview, pwd)

    # Build file list and process files in parallel
    valid_extensions = set(MEDIA_EXTENSIONS['image'] + MEDIA_EXTENSIONS['video'])
    all_files = list(source.rglob('*'))
    media_files = [f for f in all_files if f.is_file() and f.suffix.lower()[1:] in valid_extensions]

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(process_file, f, target, preview, fallback_to_mtime, remove_duplicates) for f in media_files]
        for future in futures:
            future.result()

    # Clean up empty directories
    if not preview:
        remove_empty_directories(source)

if __name__ == "__main__":
    main()