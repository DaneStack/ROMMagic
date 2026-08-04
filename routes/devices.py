from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_file, jsonify
import os
import io
import zipfile
from werkzeug.utils import secure_filename
from flask_login import login_required
from models import Device
from extensions import db

devices_bp = Blueprint('devices', __name__)

@devices_bp.route('/')
@login_required
def index():
    devices = Device.query.all()
    bios_dir = os.path.join(current_app.config['ROM_UPLOAD_PATH'], 'bios')
    has_bios = {}
    for device in devices:
        bios_filename = f"bios-{secure_filename(device.name)}.zip"
        bios_path = os.path.join(bios_dir, bios_filename)
        has_bios[device.id] = os.path.exists(bios_path)
        
    return render_template('devices/index.html', devices=devices, has_bios=has_bios)

@devices_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if request.method == 'POST':
        name = request.form.get('name')
        if not name:
            flash('Device name is required.', 'error')
        elif Device.query.filter_by(name=name).first():
            flash('Device name already exists.', 'error')
        else:
            device = Device(name=name)
            db.session.add(device)
            db.session.commit()
            flash('Device added successfully.', 'success')
            return redirect(url_for('devices.index'))
            
    return render_template('devices/form.html', title="Add Device", device=None)

@devices_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    device = db.session.get(Device, id)
    if not device:
        flash('Device not found.', 'error')
        return redirect(url_for('devices.index'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        if not name:
            flash('Device name is required.', 'error')
        else:
            existing = Device.query.filter_by(name=name).first()
            if existing and existing.id != id:
                flash('Device name already exists.', 'error')
            else:
                device.name = name
                db.session.commit()
                flash('Device updated successfully.', 'success')
                return redirect(url_for('devices.index'))
                
    return render_template('devices/form.html', title="Edit Device", device=device)

@devices_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    device = db.session.get(Device, id)
    if device:
        db.session.delete(device)
        db.session.commit()
        flash('Device deleted successfully.', 'success')
    else:
        flash('Device not found.', 'error')
    return redirect(url_for('devices.index'))

@devices_bp.route('/upload_bios/<int:id>', methods=['POST'])
@login_required
def upload_bios(id):
    device = db.session.get(Device, id)
    if not device:
        flash('Device not found.', 'error')
        return redirect(url_for('devices.index'))
        
    if 'bios_file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('devices.index'))
        
    file = request.files['bios_file']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('devices.index'))
        
    if file and file.filename.lower().endswith('.zip'):
        bios_dir = os.path.join(current_app.config['ROM_UPLOAD_PATH'], 'bios')
        os.makedirs(bios_dir, exist_ok=True)
        
        filename = f"bios-{secure_filename(device.name)}.zip"
        file_path = os.path.join(bios_dir, filename)
        file.save(file_path)
        flash(f'BIOS uploaded successfully for {device.name}.', 'success')
    else:
        flash('Only .zip files are allowed for BIOS.', 'error')
        
    return redirect(url_for('devices.index'))

@devices_bp.route('/download_bios/<int:id>')
@login_required
def download_bios(id):
    device = db.session.get(Device, id)
    if not device:
        flash('Device not found.', 'error')
        return redirect(url_for('devices.index'))
        
    bios_filename = f"bios-{secure_filename(device.name)}.zip"
    bios_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], 'bios', bios_filename)
    
    if not os.path.exists(bios_path):
        flash('BIOS file not found for this device.', 'error')
        return redirect(url_for('devices.index'))
        
    return send_file(
        bios_path,
        mimetype='application/zip',
        as_attachment=True,
        download_name=bios_filename
    )

@devices_bp.route('/delete_bios/<int:id>', methods=['POST'])
@login_required
def delete_bios(id):
    device = db.session.get(Device, id)
    if not device:
        flash('Device not found.', 'error')
        return redirect(url_for('devices.index'))
        
    bios_filename = f"bios-{secure_filename(device.name)}.zip"
    bios_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], 'bios', bios_filename)
    
    if os.path.exists(bios_path):
        try:
            os.remove(bios_path)
            flash(f'BIOS deleted successfully for {device.name}.', 'success')
        except OSError as e:
            flash(f'Error deleting BIOS file: {e}', 'error')
    else:
        flash('BIOS file not found.', 'error')
        
    return redirect(url_for('devices.index'))

@devices_bp.route('/api/<int:id>/platforms')
@devices_bp.route('/<int:id>/platforms')
@login_required
def api_platforms(id):
    device = db.session.get(Device, id)
    if not device:
        return jsonify({'error': 'Device not found'}), 404
    platforms = device.platforms.all()
    res = []
    for p in platforms:
        res.append({
            'id': p.id,
            'name': p.name,
            'allowed_extensions': p.allowed_extensions,
            'folder_name': p.get_folder_name,
            'device_id': p.device_id,
            'scraper': p.scraper
        })
    return jsonify(res)
