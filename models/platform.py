from extensions import db

# Predefined platforms that match TheGamesDB API names for reliable scraping.
# Each entry maps a display name to its default allowed file extensions.
PREDEFINED_PLATFORMS = {
    'Sony Playstation 2': 'iso, bin, cue, img, gz, cso',
    'Nintendo Game Boy Advance': 'gba, zip, 7z',
    'Nintendo Switch': 'nsp, xci, nsz, xcz',
    'Sony Playstation Portable': 'iso, cso, pbp, chd',
    'Nintendo GameCube': 'rvz',
}

class Platform(db.Model):
    __tablename__ = 'platforms'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    allowed_extensions = db.Column(db.String(256), nullable=True)
    folder_name = db.Column(db.String(128), nullable=True)
    scraper = db.Column(db.String(64), nullable=False, default='thegamesdb')
    
    roms = db.relationship('Rom', backref='platform', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def get_folder_name(self):
        from werkzeug.utils import secure_filename
        if self.folder_name:
            return secure_filename(self.folder_name)
        return secure_filename(self.name.lower().replace(' ', '_'))
