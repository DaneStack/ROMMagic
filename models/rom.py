from extensions import db

class Rom(db.Model):
    __tablename__ = 'roms'
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(256), nullable=False)
    original_filename = db.Column(db.String(256), nullable=True)
    platform_id = db.Column(db.Integer, db.ForeignKey('platforms.id'), nullable=False)
    game_title = db.Column(db.String(256), nullable=True)
    search_keywords = db.Column(db.String(256), nullable=True)
    cover_image_url = db.Column(db.String(512), nullable=True)
    esrb_rating = db.Column(db.String(64), nullable=True)
    genres = db.Column(db.String(512), nullable=True)
    description = db.Column(db.Text, nullable=True)
