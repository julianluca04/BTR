import os
import hashlib
import shutil

def get_file_hash(file_path):
    """Generates a SHA-256 hash for a file's content."""
    hasher = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (PermissionError, OSError):
        return None

def organize_all_duplicates(target_directory):
    if not os.path.exists(target_directory):
        print(f"Error: Path '{target_directory}' not found.")
        return

    # 1. Identify Duplicates
    hashes = {} 
    print(f"Scanning: {target_directory}...")

    for root, _, files in os.walk(target_directory):
        # Safety: Don't scan the folder we are moving things into
        if "duplicates_found" in root:
            continue
            
        for filename in files:
            if filename.startswith('.'): continue
            path = os.path.join(root, filename)
            f_hash = get_file_hash(path)
            
            if f_hash:
                if f_hash in hashes:
                    hashes[f_hash].append(path)
                else:
                    hashes[f_hash] = [path]

    # 2. Setup Duplicate Root Folder
    dup_root = os.path.join(target_directory, "duplicates_found")
    
    found_any = False
    group_count = 1

    for f_hash, paths in hashes.items():
        if len(paths) > 1:
            found_any = True
            # Create a subfolder for this specific group (contains all versions)
            group_folder = os.path.join(dup_root, f"group_{group_count}")
            os.makedirs(group_folder, exist_ok=True)
            
            print(f"\nMoving Group {group_count} (Identical Content):")
            
            for file_path in paths:
                file_name = os.path.basename(file_path)
                dest = os.path.join(group_folder, file_name)
                
                # Handle potential filename collisions within the same hash group
                # (e.g., if two files have the same name but are in different subdirectories)
                if os.path.exists(dest):
                    base, ext = os.path.splitext(file_name)
                    dest = os.path.join(group_folder, f"{base}_copy{ext}")
                
                try:
                    shutil.move(file_path, dest)
                    print(f"  -> Moved: {file_name}")
                except Exception as e:
                    print(f"  [!] Error moving {file_name}: {e}")
            
            group_count += 1

    if not found_any:
        print("\n✨ No duplicates found. No files were moved.")
    else:
        print(f"\n✅ Done! Total groups moved: {group_count - 1}")
        print(f"All files with identical content are now in: {dup_root}")

if __name__ == "__main__":
    # Your specific path
    path = r'/Users/foml/coding/MSP/year_3/Thesis work/BTR/experiments/LoRa/julian/byte /data/LoRa/single_byte_fragments/best'
    organize_all_duplicates(path)