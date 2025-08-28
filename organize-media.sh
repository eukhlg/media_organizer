#!/bin/sh

set -e

# === HELP & VALIDATION ===
if [ $# -lt 2 ]; then
  echo "Usage: $0 <source_dir> <target_dir> [--preview] [--fallback-to-mtime]"
  echo "Moves image files based on EXIF date into <target>/YYYY/MM/"
  echo "Conflicts resolved by hash. Identical files skipped."
  exit 1
fi

SOURCE="$(realpath "$1")"
TARGET="$(realpath "$2")"
PREVIEW=false
FALLBACK_TO_MTIME=false

if [ "$3" == "--preview" ]; then
  PREVIEW=true
fi

if [ "$4" == "--fallback-to-mtime" ]; then
  FALLBACK_TO_MTIME=true
fi

if [ ! -d "$SOURCE" ]; then
  echo "Source directory does not exist: $SOURCE"
  exit 2
fi

mkdir -p "$TARGET"

echo "Source: $SOURCE"
echo "Target: $TARGET"
$PREVIEW && echo "[PREVIEW MODE — No files will be moved]"

# Transliterate Russian characters to English
transliterate_ru_to_en() {
  echo "$1" | sed -e '
  s/А/A/g; s/Б/B/g; s/В/V/g; s/Г/G/g; s/Д/D/g;
  s/Е/E/g; s/Ё/E/g; s/Ж/Zh/g; s/З/Z/g; s/И/I/g;
  s/Й/Y/g; s/К/K/g; s/Л/L/g; s/М/M/g; s/Н/N/g;
  s/О/O/g; s/П/P/g; s/Р/R/g; s/С/S/g; s/Т/T/g;
  s/У/U/g; s/Ф/F/g; s/Х/Kh/g; s/Ц/Ts/g; s/Ч/Ch/g;
  s/Ш/Sh/g; s/Щ/Shch/g; s/Ы/Y/g; s/Э/E/g; s/Ю/Yu/g; s/Я/Ya/g;

  s/а/a/g; s/б/b/g; s/в/v/g; s/г/g/g; s/д/d/g;
  s/е/e/g; s/ё/e/g; s/ж/zh/g; s/з/z/g; s/и/i/g;
  s/й/y/g; s/к/k/g; s/л/l/g; s/м/m/g; s/н/n/g;
  s/о/o/g; s/п/p/g; s/р/r/g; s/с/s/g; s/т/t/g;
  s/у/u/g; s/ф/f/g; s/х/kh/g; s/ц/ts/g; s/ч/ch/g;
  s/ш/sh/g; s/щ/shch/g; s/ы/y/g; s/э/e/g; s/ю/yu/g; s/я/ya/g;
  s/ъ//g; s/ь//g;
  '
}

# === FUNCTION: Get SHA256 ===
sha256sum_file() {
  sha256sum "$1" | awk '{print $1}'
}

# === MAIN LOOP ===
find "$SOURCE" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mpg' -o -iname '*.avi' \) | while read -r src_file; do

  # === Determine extension and select tag accordingly ===
  ext="${src_file##*.}"
  ext_lc=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

  if [[ "$ext_lc" == "jpg" || "$ext_lc" == "jpeg" || "$ext_lc" == "png" ]]; then
    exif_tag="DateTimeOriginal"
  elif [[ "$ext_lc" == "mp4" || "$ext_lc" == "mov" || "$ext_lc" == "mpg" || "$ext_lc" == "avi" ]]; then
    exif_tag="CreateDate"
  else
    echo "[!] Unsupported extension: $src_file"
    continue
  fi

  # === Get file base name and thumbnail file name ===
  base_name=$(basename "$src_file")
  thm_file="$(dirname "$src_file")/${base_name%.*}.THM"
  json_file="$(dirname "$src_file")/${base_name}.json"

  # === Extract EXIF/Video date ===
  exif_date=$(exiftool -d "%Y-%m-%d %H:%M:%S" "-$exif_tag" -s3 "$src_file")

  # === Get thumbnail date if it exists ===
  if [[ -f "$thm_file" ]]; then
    thm_date=$(exiftool -d "%Y-%m-%d %H:%M:%S" -DateTimeOriginal -s3 "$thm_file")
    if [[ -n "$thm_date" && "$thm_date" != "0000:00:00 00:00:00" && "$thm_date" != "0000-00-00 00:00:00" ]]; then
      exif_date="$thm_date"
      echo "[~] Using .THM metadata: $thm_file → $exif_date"
    fi
  fi

  # === Fallback to file mtime if needed ===
  if [[ -z "$exif_date" || "$exif_date" == "0000:00:00 00:00:00" || "$exif_date" == "0000-00-00 00:00:00" ]]; then
    if $FALLBACK_TO_MTIME; then 
      exif_date=$(date -r "$src_file" +"%Y-%m-%d %H:%M:%S")
      echo "[~] Fallback to file timestamp: $src_file → $exif_date"
    else
      echo "[!] Skipping: $src_file (no valid date)"
      continue
    fi
  fi

  # Parse year/month
  year=$(echo "$exif_date" | cut -d'-' -f1)
  month=$(echo "$exif_date" | cut -d'-' -f2)
  dest_dir="$TARGET/$year/$month"

  # Create target directory if it doesn't exist and if not in preview mode
  if ! $PREVIEW; then
    mkdir -p "$dest_dir"
  fi

  # Ensure file timestamps match EXIF
  # Get current file mod time (YYYY-MM-DD HH:MM:SS)
  file_time=$(date -r "$src_file" +"%Y-%m-%d %H:%M:%S")
  if [[ "$file_time" != "$exif_date" ]]; then
    $PREVIEW && echo "[~] Would update timestamp: $src_file"
    $PREVIEW && [ -f "$thm_file" ] && echo "[~] Would update timestamp: $thm_file"
    $PREVIEW && [ -f "$json_file" ] && echo "[~] Would update timestamp: $json_file"
    if ! $PREVIEW; then
      if [[ "$ext_lc" == "jpg" || "$ext_lc" == "jpeg" || "$ext_lc" == "png" ]]; then
        exiftool "-FileModifyDate<DateTimeOriginal" "-FileCreateDate<DateTimeOriginal" -overwrite_original "$src_file" 2>&1
      elif [[ "$ext_lc" == "mp4" || "$ext_lc" == "mov" || "$ext_lc" == "mpg" ]]; then
        exiftool "-FileModifyDate<CreateDate" "-FileCreateDate<CreateDate" -overwrite_original "$src_file" 2>&1
      fi
      touch -d "$exif_date" "$src_file"
      echo "[~] Updated timestamp: $src_file"
      if [[ -f "$thm_file" ]]; then
        touch -d "$exif_date" "$thm_file"
        echo "[~] Updated timestamp: $thm_file"
      fi
      if [[ -f "$json_file" ]]; then
        touch -d "$exif_date" "$json_file"
        echo "[~] Updated timestamp: $json_file"
      fi
    fi
  fi

  # Determine target file path
  tgt_file="$dest_dir/$base_name"

  # Transliterate if Russian characters detected
  if [[ "$base_name" =~ [А-Яа-я] ]]; then
    tgt_file="$(dirname "$tgt_file")/$(transliterate_ru_to_en "$(basename "$tgt_file")")"
    thm_file="$(dirname "$thm_file")/$(transliterate_ru_to_en "$(basename "$thm_file")")"
  fi

  if [ ! -f "$tgt_file" ]; then
    if $PREVIEW; then
      echo "[+] Would move: $base_name → $year/$month/$(basename "$tgt_file")"
      [ -f "$thm_file" ] && echo "[+] Would move thumbnail: ${base_name%.*}.THM → $year/$month/$(transliterate_ru_to_en "$(basename "$thm_file")")"
    fi
    if ! $PREVIEW; then
      mv "$src_file" "$tgt_file"
      echo "[+] Moved: $base_name → $year/$month/$(basename "$tgt_file")"
      if [ -f "$thm_file" ]; then
        mv "$thm_file" "$dest_dir"
        echo "[+] Moved thumbnail: ${base_name%.*}.THM → $year/$month/$(transliterate_ru_to_en "$(basename "$thm_file")")"
      fi
    fi
  else
    # Check for hash match
    src_hash=$(sha256sum_file "$src_file")
    tgt_hash=$(sha256sum_file "$tgt_file")

    if [ "$src_hash" == "$tgt_hash" ]; then
      echo "[=] Identical: $base_name (skipped)"
    else
      # Rename and move
      ext="${base_name##*.}"
      name="${base_name%.*}"
      suffix=$(date +%Y%m%d_%H%M%S)
      new_name="${name}_copy_${suffix}.${ext}"
      new_path="$dest_dir/$new_name"

      $PREVIEW && echo "[!] Conflict: $base_name → $new_name"
      if ! $PREVIEW; then
        mv "$src_file" "$new_path"
        echo "[!] Conflict: Moved as $new_name"
      fi
    fi
  fi
done