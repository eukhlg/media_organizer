---
# 📁 Media Organizer

**Media Organizer** is a powerful and flexible Python tool that organizes your photos and videos into a structured folder hierarchy (`<target>/YYYY/MM/`) based on their metadata (EXIF, JSON, filenames, etc.).  
It handles duplicate detection, updates timestamps, and can even extract archives — all with multithreading support for speed!

---
## 🚀 Features

- 📅 Organizes files by date (`Year/Month`) based on EXIF, JSON metadata, filenames, or modification times
- 🔍 Detects and optionally removes duplicate files using SHA256 hashing
- 🗃️ Extracts archives (`.zip`, `.rar`, `.tar`, `.gz`, etc.) in-place (with password support)
- 🛠️ Fixes and updates both EXIF and filesystem timestamps
- 🌍 Transliterates Cyrillic filenames to Latin
- 🧵 Multithreaded processing (default: 2 × CPU cores)
- 🪵 Logs all operations to a central and monthly log file
- 🧹 Optionally cleans up empty directories after processing
- 🔍 Preview mode to test everything before touching your files

---
## 🧑‍💻 Requirements

- Python 3.7+
- `exiftool` installed and in your system's `PATH`
- `7z` installed (for archive extraction)
- Python dependencies:
- `transliterate`
- `rarfile`

Install dependencies with:

```bash
pip install transliterate rarfile
```

Make sure exiftool and 7z (or 7za) are accessible from your command line.
Windows users can install ExifTool and 7-Zip.

---

🧾 Usage
```bash
python media_organizer.py <source_dir> <target_dir> [OPTIONS]
```
📌 Example
```bash
python media_organizer.py /home/user/DCIM /home/user/OrganizedMedia --fallback-to-mtime --extract-archives --remove-duplicates --remove-empty-dirs --verbose
```
---

⚙️ Options

|--Option--|--Description--|
|--preview | Preview mode — no files will be moved
|--fallback-to-mtime |	Use file modification time if EXIF date is missing
|--remove-duplicates |	Remove identical files instead of skipping
|--remove-empty-dirs |	Clean up empty directories in the source folder
|--extract-archives |	Extract supported archives before processing
|--archive-password <password>	| Use a preset password for encrypted archives
|--remove-extracted	| Delete archive files after successful extraction
|--threads <num> | Number of parallel threads (default: 2 × CPU cores)
|--verbose	| Enable detailed output

---

🗂️ Archive Support

This tool can extract the following archive types:
	•	.zip
	•	.rar
	•	.tar
	•	.gz, .tgz
	•	.bz2
	•	.xz

Password-protected archives are supported using --archive-password. If omitted, the script will prompt you interactively.

---

🛡️ Duplicate Handling

If a file with the same name already exists:
- If sizes differ → file is renamed and moved to conflicts/
- If sizes match:
- Hash is calculated (SHA256)
- If identical:
  - Deleted if --remove-duplicates is used
  - Skipped otherwise

---

📑 Logging

All operations are logged to:
- media_organizer.log in the target directory
- Monthly logs inside each <target>/YYYY/MM/ folder

If logs already exist, they will be safely backed up as media_organizer.log.1, .2, etc.

---

🧠 Date Detection Strategy

The tool tries to determine the best available date for sorting media:
	1.	EXIF — DateTimeOriginal (images) or CreateDate (videos)
	2.	Associated JSON — looks for photoTakenTime.timestamp
	3.	Associated THM file (for some video formats)
	4.	Filename pattern — detects YYYYMMDD_HHMMSS
	5.	File modification time (if --fallback-to-mtime is used)

---

🌐 Transliteration

Cyrillic filenames are automatically converted to Latin (e.g., Пример.jpg → Primer.jpg) to improve cross-platform compatibility.

---

🧼 Timestamps Fix

If EXIF or derived date differs from filesystem dates, the script will update:
- EXIF DateTimeOriginal or CreateDate
- Filesystem access/modification timestamps

This ensures consistent and accurate metadata.

---

🧪 Preview Mode

Add --preview to safely test the script before moving anything:

```bash
python media_organizer.py ~/Downloads ~/Organized --preview --verbose
```

---

🔐 Tips for Archive Handling
- Use --extract-archives to scan and extract .zip, .rar, etc. before sorting
- Add --remove-extracted to delete archive files after successful extraction
- Combine with --archive-password to prefill credentials

---

🧹 Clean-Up Mode

To remove all empty directories after processing (use with care):

--remove-empty-dirs


---

📞 Support & Contribution

This project was created as a personal tool but is open to feedback, suggestions, and improvements.
Feel free to fork, adapt, or share it — just credit the original author.

---

📜 License

MIT License — free for personal and commercial use.

---

Happy organizing! 🎉

---

Let me know if you'd like this saved to a file, converted to HTML, or auto-generated into a GitHub repository layout.
