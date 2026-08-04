![ROMMagic Banner](https://iili.io/CUD7byX.png)

# ROMMagic

> [!WARNING]
> **THIS IS NOT READY FOR PUBLIC USE.** Please run this tool strictly within your local home network. Do not set up port forwarding or expose it to the public internet.

**ROMMagic** is a web-based ROM and save-file management platform built with **Flask**, **SQLAlchemy**, and **MariaDB/MySQL**. It is designed to help retro gaming enthusiasts centralize, manage, organize, and scrape metadata for their ROM collections and save files across multiple gaming devices and emulation platforms.

---

## Features

- **Device & Platform Management**: Group platforms by gaming devices (e.g. handhelds, home consoles) with custom file extension filters and folder structures.
- **Automated Scraping**: Fetch game titles, cover images, descriptions, genres, and ESRB ratings automatically via **TheGamesDB** and **ScreenScraper** APIs.
- **Save File Management**: Upload, download, and manage save files per platform and game.
- **EmulationStation XML Generator**: Generate `gamelist.xml` files for seamless integration with EmulationStation, RetroPie, Batocera, AmberELEC, or EmuELEC setups.
- **Large ROM Upload Support**: Configured to support uploading large ROM images (up to 100 GB for modern platforms like Nintendo Switch, PS2, and GameCube).
- **User Authentication**: Authentication system powered by Flask-Login with automatic initial admin account creation.
- **Database Migrations**: Built-in automated database schema migrations tool.
- **Docker-Ready**: Packaged with Dockerfile support for quick deployment.

---

## Tech Stack

- **Backend**: Python 3.14+, Flask, Flask-SQLAlchemy, Flask-Login
- **Database**: MariaDB / MySQL (via PyMySQL)
- **Image Processing**: Pillow
- **Containerization**: Docker

---

## Prerequisites

- **Python**: `3.10` or higher (if running natively)
- **Database**: Running MariaDB or MySQL instance
- **Docker**: Optional, for containerized execution

---

## Quick Start

### Method 1: Local Setup (Python Environment)

1. **Clone the repository**:
   ```bash
   git clone https://github.com/DaneStack/rommagic.git
   cd rommagic
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   Copy `.env.example` to `.env` and fill in your database credentials and optional API keys:
   ```bash
   cp .env.example .env
   ```

5. **Start the application**:
   ```bash
   python app.py
   ```
   The web application will be available at `http://localhost:5000`.

   > **Default Admin Login**:
   > - **Username**: `admin`
   > - **Password**: `admin` *(Change this in production!)*

---

### Method 2: Docker Setup

1. **Build the Docker image**:
   ```bash
   docker build -t rommagic .
   ```

2. **Run the container**:
   ```bash
   docker run -d \
     --name rommagic \
     -p 5000:5000 \
     --env-file .env \
     -v ./ROMs:/app/ROMs \
     rommagic
   ```

---

## Environment Variables Configuration

Create a `.env` file in the root directory based on `.env.example`:

| Environment Variable | Default Value | Description |
| :--- | :--- | :--- |
| `SECRET_KEY` | `default_secret` | Flask session secret key |
| `DB_HOST` | `127.0.0.1` | MariaDB / MySQL server hostname or IP |
| `DB_USER` | `root` | Database user |
| `DB_PASS` | `""` | Database password |
| `DB_NAME` | `rommagic` | Database name |
| `ROM_UPLOAD_PATH` | `ROMs` | Directory path where ROM files and BIOS are stored |
| `TIMEZONE` | `Europe/Budapest` | Default timezone setting |
| `MIGRATION_SECRET_KEY` | `dev_migration_key` | Secret key to authorize database migration execution |
| `THEGAMESDB_API_KEY` | *Optional* | API key for metadata scraping from [TheGamesDB](https://thegamesdb.net/) |
| `SCREENSCRAPER_DEV_ID` | *Optional* | Developer ID for [ScreenScraper](https://www.screenscraper.fr/) |
| `SCREENSCRAPER_DEV_PASSWORD`| *Optional* | Developer Password for ScreenScraper |
| `SCREENSCRAPER_USER` | *Optional* | Optional registered user account for ScreenScraper |
| `SCREENSCRAPER_PASSWORD` | *Optional* | Optional registered user password for ScreenScraper |

---

## Project Structure

```
rommagic/
├── app.py              # Application factory & entry point
├── config.py           # App configuration settings & env loader
├── extensions.py       # Flask extensions (SQLAlchemy, LoginManager)
├── migration.py        # Database schema migration utilities
├── Dockerfile          # Docker setup file
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variables template
├── models/             # Database models (User, Device, Platform, Rom, Task)
├── routes/             # Route Blueprints (auth, main, devices, platforms, roms, saves)
├── utils/              # Helper utilities (Scrapers, ES XML generator, Cache)
├── static/             # Static web assets (CSS, JS, Images)
└── templates/          # HTML templates (Jinja2)
```

---

## Database Migrations

ROMMagic automatically verifies database tables on startup. If schema updates are needed, you can trigger database migrations via endpoint:

```bash
# Via GET Request
curl "http://localhost:5000/migration?key=YOUR_MIGRATION_SECRET_KEY"

# Or Via POST Header
curl -X POST http://localhost:5000/migration \
  -H "X-Migration-Key: YOUR_MIGRATION_SECRET_KEY"
```

---

## License

This project is open-source. Feel free to contribute or adapt it for your home server setup!
