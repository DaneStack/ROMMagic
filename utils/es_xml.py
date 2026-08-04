import os
import urllib.request
from xml.etree import ElementTree as ET
from xml.dom import minidom
from PIL import Image

def download_and_convert_cover_image(app, platform_dir, filename, image_url):
    """
    Downloads the cover image from the URL and saves it as a PNG locally.
    Returns the local filename relative to the platform directory (e.g. 'images/game-image.png')
    or None on failure.
    """
    if not image_url:
        return None

    upload_path = app.config.get('ROM_UPLOAD_PATH')
    images_dir = os.path.join(upload_path, platform_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)

    base, _ = os.path.splitext(filename)
    local_image_name = f"{base}.png"
    local_image_path = os.path.join(images_dir, local_image_name)

    try:
        import io
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(image_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                # Read response bytes and wrap in BytesIO to avoid seek issues
                img_bytes = response.read()
                img = Image.open(io.BytesIO(img_bytes))
                # Convert to RGB if necessary (e.g. CMYK or Palette to RGB, since PNG doesn't support writing CMYK directly)
                if img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGB')
                img.save(local_image_path, format="PNG")
                return f"images/{local_image_name}"
    except Exception as e:
        app.logger.error(f"Error downloading or converting image {image_url}: {e}")

    return None

def delete_rom_files(app, rom):
    """
    Deletes the ROM file and its associated cover image(s) from disk.
    Ensures cover images are not deleted if another ROM in the same platform references them.
    """
    if not rom or not rom.platform:
        return

    upload_path = app.config.get('ROM_UPLOAD_PATH')
    platform_dir = rom.platform.get_folder_name
    platform_path = os.path.join(upload_path, platform_dir)
    images_dir = os.path.join(platform_path, 'images')

    # 1. Delete main ROM file from disk
    if rom.filename:
        file_path = os.path.join(platform_path, rom.filename)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            app.logger.error(f"Error deleting ROM file {file_path}: {e}")

    # 2. Collect candidate cover image filenames to delete
    candidate_images = set()

    if rom.cover_image_url:
        if '/roms/media/' in rom.cover_image_url:
            parts = rom.cover_image_url.rsplit('/', 1)
            if len(parts) > 1:
                candidate_images.add(parts[1])
        elif 'images/' in rom.cover_image_url:
            parts = rom.cover_image_url.rsplit('images/', 1)
            if len(parts) > 1:
                candidate_images.add(parts[1].rsplit('/', 1)[-1])
        elif not rom.cover_image_url.startswith(('http://', 'https://', '/')):
            candidate_images.add(os.path.basename(rom.cover_image_url))

    if rom.filename:
        base, _ = os.path.splitext(rom.filename)
        for ext in ['.png', '.jpg', '.jpeg', '.webp']:
            candidate_images.add(f"{base}{ext}")

    if not candidate_images or not os.path.exists(images_dir):
        return

    # Check if any other ROM in the same platform references any candidate image
    from models import Rom
    other_roms = Rom.query.filter(Rom.platform_id == rom.platform_id, Rom.id != rom.id).all()

    other_image_names = set()
    other_filename_bases = set()

    for other in other_roms:
        if other.cover_image_url:
            if '/roms/media/' in other.cover_image_url:
                other_image_names.add(other.cover_image_url.rsplit('/', 1)[-1])
            elif 'images/' in other.cover_image_url:
                other_image_names.add(other.cover_image_url.rsplit('images/', 1)[-1].rsplit('/', 1)[-1])
            elif not other.cover_image_url.startswith(('http://', 'https://', '/')):
                other_image_names.add(os.path.basename(other.cover_image_url))
        if other.filename:
            other_filename_bases.add(os.path.splitext(other.filename)[0])

    for img_name in candidate_images:
        img_path = os.path.join(images_dir, img_name)
        if os.path.isfile(img_path):
            img_base, _ = os.path.splitext(img_name)
            # Skip if referenced by or matching another ROM
            if img_name in other_image_names or img_base in other_filename_bases:
                continue
            try:
                os.remove(img_path)
            except Exception as e:
                app.logger.error(f"Error deleting cover image {img_path}: {e}")

    # Remove images directory if empty
    try:
        if os.path.exists(images_dir) and not os.listdir(images_dir):
            os.rmdir(images_dir)
    except Exception as e:
        app.logger.error(f"Error removing empty images directory {images_dir}: {e}")

def generate_gamelist_xml(app, platform):
    """
    Generates EmulationStation gamelist.xml for a platform based on its ROMs.
    """
    from models import Rom
    
    platform_dir = platform.get_folder_name
    upload_path = app.config.get('ROM_UPLOAD_PATH')
    platform_path = os.path.join(upload_path, platform_dir)
    
    if not os.path.exists(platform_path):
        os.makedirs(platform_path, exist_ok=True)

    xml_path = os.path.join(platform_path, 'gamelist.xml')

    game_list_element = ET.Element('gameList')

    roms = Rom.query.filter_by(platform_id=platform.id).all()
    for rom in roms:
        game_element = ET.SubElement(game_list_element, 'game')

        path_element = ET.SubElement(game_element, 'path')
        path_element.text = f"./{rom.filename}"

        if rom.game_title:
            name_element = ET.SubElement(game_element, 'name')
            name_element.text = rom.game_title

        if rom.description:
            desc_element = ET.SubElement(game_element, 'desc')
            desc_element.text = rom.description

        if rom.cover_image_url:
            # Check if it's the local media URL we generate
            # In our new implementation, cover_image_url will look like: 
            # /roms/media/<platform_id>/<image_filename>
            if '/roms/media/' in rom.cover_image_url:
                local_rel = rom.cover_image_url.split('/roms/media/')[1]
                # local_rel is <platform_id>/<image_filename>
                parts = local_rel.split('/', 1)
                if len(parts) == 2:
                    image_filename = parts[1] # e.g. game-image.png
                    image_element = ET.SubElement(game_element, 'image')
                    image_element.text = f"./images/{image_filename}"

        if rom.esrb_rating:
            rating_element = ET.SubElement(game_element, 'rating')
            # EmulationStation rating is usually a float, but we might just put the ESRB string in <rating> or <kidgame> etc.
            # ESRB is often put in <desc> or as text, but EmulationStation themes handle <rating> as a float (0.0 - 1.0).
            # Some themes support custom fields or standard <genre>.
            # Let's just output it if we have it, although ES might not natively use ESRB string in <rating>.
            pass # We'll skip <rating> for string ESRB to avoid breaking standard float parsing.
            
        if rom.genres:
            genre_element = ET.SubElement(game_element, 'genre')
            genre_element.text = rom.genres

    # Format the XML with indentation
    xml_str = ET.tostring(game_list_element, encoding='utf-8')
    parsed = minidom.parseString(xml_str)
    pretty_xml = parsed.toprettyxml(indent="\t")

    try:
        with open(xml_path, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
    except Exception as e:
        app.logger.error(f"Error writing gamelist.xml for {platform.name}: {e}")
