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

# Media file extensions
MEDIA_EXTENSIONS = {
    'image': ['jpg', 'jpeg', 'png', 'heic', 'heif', 'webp'],
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

def print_usage():
    """Prints usage instructions."""
    print("Usage: script.py <source_dir> <target_dir> [--preview] [--fallback-to-mtime] [--remove-duplicates] [--extract-archives] [--password <password>]")
    print("Organizes media files based on EXIF or extracted metadata into <target>/YYYY/MM/")
    print("Duplicates are handled by comparing hashes.")

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
    """Parses JSON metadata to retrieve photo taken time."""
    with open(json_file, 'r') as jf:
        data = json.load(jf)
        formatted_time = data.get('photoTakenTime', {}).get('formatted')
        if formatted_time:
            return datetime.strptime(formatted_time[:-4], "%d %b. %Y, %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
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
    subprocess.run(cmd, capture_output=True)
    os.utime(file_path, (datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S').timestamp(),) * 2)

def log_move(global_log_path, month_log_path, src, dst):
    """Logs file movement details to both global and monthly logs."""
    entry = f"{datetime.now().isoformat()} | {src} -> {dst}\n"
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
            if extract_archive_with_password(archive_path, output_folder, pwd):
                print(f"[+] Successfully extracted {archive_path} with provided password.")
                return True
            else:
                print(f"[!] Failed to extract {archive_path} with provided password.")
                return False
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

def process_file(src_file, target_root, preview=False, fallback_to_mtime=False, remove_duplicates=False):
    """Processes individual media files, handling metadata extraction and duplicate resolution."""
    ext = src_file.suffix.lower()[1:]
    base_name = src_file.name
    json_file = src_file.with_name(src_file.stem + '.json')
    thm_file = src_file.with_suffix('.THM')

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

  
    # Create destination paths
    year, month = exif_date.split('-')[:2]
    dest_dir = target_root / year / month
    dest_dir.mkdir(parents=True, exist_ok=True)
    month_log_file = dest_dir / "media_organizer.log"

    # Target file path setup
    tgt_file = dest_dir / base_name
    if re.search(r'[А-Яа-я]', base_name):
        tgt_file = dest_dir / transliterate_ru_to_en(base_name)

    # Backup existing log file if present
    if month_log_file.exists():
        backup_existing_log(month_log_file)

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
                    src_file.unlink()  # Remove duplicate
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

    # Move or simulate move operation
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

def process_directory(source_dir, target_dir, preview=False, fallback_to_mtime=False, remove_duplicates=False, extract_archives=False, pwd=None):
    """Main routine to organize media files recursively."""
    global global_log_file

    # Clean up previous logs
    global_log_file = target_dir / "media_organizer.log"
    global_log_file.unlink(missing_ok=True)

    # Process archives first
    if extract_archives:
        extract_archives_in_place(source_dir, global_log_file, preview, pwd)

    # Walk through directories and process each media file
    valid_extensions = set(MEDIA_EXTENSIONS['image'] + MEDIA_EXTENSIONS['video'])
    for src_file in source_dir.rglob('*'):
        if src_file.is_file() and src_file.suffix.lower()[1:] in valid_extensions:
            process_file(src_file, target_dir, preview, fallback_to_mtime, remove_duplicates)

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
                        print(f"[+] Removed archive file: {archive}")
                else:
                    print(f"[~] Would unpack {archive}")
        except Exception as e:
            print(f"[!] Error extracting {archive}: {e}")

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

    if not source.is_dir():
        print(f"Source directory does not exist: {source}")
        sys.exit(2)

    print(f"Source: {source}")
    print(f"Target: {target}")
    if preview:
        print("[PREVIEW MODE — No files will be moved]")

    target.mkdir(parents=True, exist_ok=True)

    # Parallelize directory processing
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = []
        for root, _, _ in os.walk(source):
            dir_path = Path(root)
            future = executor.submit(process_directory, dir_path, target, preview, fallback_to_mtime, remove_duplicates, extract_archives, pwd)
            futures.append(future)
        for future in futures:
            future.result()

if __name__ == "__main__":
    main()