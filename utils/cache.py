import os

def invalidate_platform_cache(app, platform_folder):
    """
    Invalidates the cached ROMs ZIP file for a given platform.
    Deletes the file if it exists.
    """
    if not platform_folder:
        return
        
    cache_path = os.path.join(
        app.config['ROM_UPLOAD_PATH'], 
        'temp', 
        f'{platform_folder}_roms_cached.zip'
    )
    
    if os.path.exists(cache_path):
        try:
            os.remove(cache_path)
            app.logger.info(f"Invalidated cache: {cache_path}")
        except Exception as e:
            app.logger.error(f"Error invalidating cache {cache_path}: {e}")
