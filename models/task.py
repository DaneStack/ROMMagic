from extensions import db
from datetime import datetime

class Task(db.Model):
    __tablename__ = 'tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    task_type = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(64), nullable=False, default='pending')
    progress = db.Column(db.Integer, nullable=False, default=0)
    result_path = db.Column(db.String(512), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
