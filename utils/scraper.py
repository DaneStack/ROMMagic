import os
import re
import urllib.request
import urllib.parse
import json
import logging

logger = logging.getLogger(__name__)

# Module-level caches to avoid repeated API calls
_genre_cache = {}
_platform_id_cache = {}

SCREENSCRAPER_SYSTEM_IDS = {
    'Sony Playstation 2': 58,
    'Nintendo Game Boy Advance': 12,
    'Nintendo Switch': 491,
    'Sony Playstation Portable': 61,
    'Nintendo GameCube': 13,
}

def clean_filename(filename):
    """
    Cleans a game filename to produce a search query for the API.
    Removes the file extension, text inside parenthesis/brackets, and replaces
    underscores/dashes with spaces.
    """
    # Remove extension
    name, _ = os.path.splitext(filename)
    # Remove content inside parentheses (...) and brackets [...]
    name = re.sub(r'\(.*?\)|\[.*?\]', '', name)
    # Replace underscores and dashes with spaces
    name = name.replace('_', ' ').replace('-', ' ')
    
    # Remove multi-language concatenated list like EnJaFrDeEsIt or EnFrDeEsIt
    name = re.sub(r'\b((?:En|Ja|Fr|De|Es|It|Nl|Pt|Sv|No|Da|Fi|Pl|Ru|Ko|Zh){2,})\b', '', name, flags=re.IGNORECASE)
    
    # Remove trailing/embedded region suffixes and metadata (including Australia, UK, etc.)
    name = re.sub(r'\b(USA|Europe|Japan|EUR|JPN|Asia|World|Australia|UK|Germany|France|Spain|Italy|Sweden|Russia|China|Korea|Rev\s*\d+|Beta\s*\d*)\b', '', name, flags=re.IGNORECASE)
    
    # Remove version numbers like v1, v2.0, V1.1
    name = re.sub(r'\bv\d+(\.\d+)*\b', '', name, flags=re.IGNORECASE)
    # Remove multiple spaces and strip
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _generate_trimmed_queries(cleaned_name):
    """
    Generates progressively shorter search queries by dropping words from the end.
    For example, 'Super Mario Bros 3 Special' yields:
      - 'Super Mario Bros 3'
      - 'Super Mario Bros'
      - 'Super Mario'
      - 'Super'
    Stops when no words would remain.
    """
    words = cleaned_name.split()
    queries = []
    # Start dropping from the last word, stop before going below 1 word
    for length in range(len(words) - 1, 0, -1):
        queries.append(' '.join(words[:length]))
    return queries

def _make_api_request(url, params):
    """
    Helper to make an API request and return the parsed JSON response.
    Returns None on failure.
    """
    try:
        url_parts = list(urllib.parse.urlparse(url))
        # Use quote_via=urllib.parse.quote to encode spaces as %20 instead of +
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        url_parts[4] = query
        full_url = urllib.parse.urlunparse(url_parts)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        req = urllib.request.Request(full_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                resp_data = response.read()
                # Decompress if the response is gzip compressed
                if response.info().get('Content-Encoding') == 'gzip':
                    import gzip
                    resp_data = gzip.decompress(resp_data)
                
                return json.loads(resp_data.decode('utf-8'))
    except Exception as e:
        logger.error(f"API request error for '{url}': {e}")
    
    return None

def _fetch_genre_map(api_key):
    """
    Fetches the full genre list from TheGamesDB /v1/Genres endpoint.
    Caches the result in a module-level dict so subsequent calls are free.
    Returns a dict mapping genre ID (int) to genre name (str).
    """
    global _genre_cache
    
    if _genre_cache:
        return _genre_cache
    
    url = "https://api.thegamesdb.net/v1/Genres"
    params = {"apikey": api_key}
    
    data = _make_api_request(url, params)
    if data and "data" in data:
        genres = data["data"].get("genres", {})
        for genre_id, genre_info in genres.items():
            _genre_cache[int(genre_id)] = genre_info.get("name", "Unknown")
    
    return _genre_cache

def _fetch_platform_id(platform_name, api_key):
    """
    Looks up a TheGamesDB platform ID by name using the /v1/Platforms/ByPlatformName endpoint.
    Caches results in a module-level dict so subsequent calls for the same name are free.
    Returns the platform ID (int) or None if not found.
    """
    global _platform_id_cache

    if not platform_name:
        return None

    cache_key = platform_name.lower().strip()
    if cache_key in _platform_id_cache:
        return _platform_id_cache[cache_key]

    url = "https://api.thegamesdb.net/v1/Platforms/ByPlatformName"
    params = {
        "apikey": api_key,
        "name": platform_name
    }

    data = _make_api_request(url, params)
    if data and "data" in data:
        platforms = data["data"].get("platforms", [])
        if platforms:
            # Pick the best match: prefer exact (case-insensitive) match, otherwise first result
            best = None
            for p in platforms:
                p_name = (p.get("name") or "").lower().strip()
                if p_name == cache_key:
                    best = p
                    break
            if best is None:
                best = platforms[0]
            platform_id = best.get("id")
            if platform_id is not None:
                _platform_id_cache[cache_key] = int(platform_id)
                return _platform_id_cache[cache_key]

    # Cache the miss so we don't keep retrying
    _platform_id_cache[cache_key] = None
    return None

def _resolve_genres(genre_ids, api_key):
    """
    Converts a list of genre ID integers into a comma-separated string
    of human-readable genre names.
    """
    if not genre_ids:
        return None
    
    genre_map = _fetch_genre_map(api_key)
    if not genre_map:
        return None
    
    names = []
    for gid in genre_ids:
        name = genre_map.get(int(gid))
        if name:
            names.append(name)
    
    return ", ".join(names) if names else None

def _score_game_title(title, query):
    """
    Helper to score and rank returned game titles against the query.
    Prefers clean titles over Demo/Greatest Hits variations when the query doesn't ask for them.
    """
    title_lower = (title or "").lower().strip()
    query_lower = (query or "").lower().strip()
    
    score = 100
    
    # Penalize demo/sample/prototype/promo versions if not requested
    demo_indicators = ["demo", "disc", "sample", "promo", "preview", "prototype", "trial", "beta"]
    for indicator in demo_indicators:
        if indicator in title_lower and indicator not in query_lower:
            score -= 50
            
    # Penalize edition variations like greatest hits, platinum, player's choice if not requested
    edition_indicators = ["greatest hits", "platinum", "player's choice", "classic", "classics", "essential", "essentials"]
    for indicator in edition_indicators:
        if indicator in title_lower and indicator not in query_lower:
            score -= 20
            
    # Penalize if significant query words are missing from the game title
    stop_words = {"the", "and", "of", "a", "to", "in", "for", "on", "with", "at", "by", "or", "an"}
    query_words = [w for w in query_lower.split() if w not in stop_words and len(w) > 1]
    for qw in query_words:
        if qw not in title_lower:
            score -= 30
    
    # Prefer closer string length to avoid matching subtitles
    len_diff = abs(len(title_lower) - len(query_lower))
    score -= len_diff
    
    # If the title starts with the query or query starts with the title, bonus
    if title_lower.startswith(query_lower) or query_lower.startswith(title_lower):
        score += 10
        
    # If exact alphanumeric match, huge bonus
    clean_title = ''.join(c for c in title_lower if c.isalnum())
    clean_query = ''.join(c for c in query_lower if c.isalnum())
    if clean_title == clean_query:
        score += 100
        
    return score


def _query_api_for_game(name, api_key, platform_id=None):
    """
    Performs a single API query for a game name and returns the parsed result dict,
    or None if no match was found.
    If platform_id is provided, results are filtered to that platform.
    """
    url = "https://api.thegamesdb.net/v1/Games/ByGameName"
    params = {
        "apikey": api_key,
        "name": name,
        "fields": "genres,overview,rating",
        "include": "boxart"
    }
    if platform_id is not None:
        params["filter[platform]"] = str(platform_id)
    
    try:
        data = _make_api_request(url, params)
        if not data or "data" not in data:
            return None
        
        games = data["data"].get("games", [])
        if not games:
            return None
        
        # Score and rank games to select the best match (avoid Greatest Hits, Demo Disc, etc.)
        scored_games = []
        for g in games:
            score = _score_game_title(g.get("game_title"), name)
            scored_games.append((score, g))
        
        scored_games.sort(key=lambda x: x[0], reverse=True)
        game = scored_games[0][1]
        game_id = str(game.get("id", ""))
        
        result = {
            "game_title": game.get("game_title"),
            "description": game.get("overview") or game.get("description") or game.get("summary"),
            "esrb_rating": game.get("rating"),
            "cover_image_url": None,
            "genres": None
        }
        
        # Extract cover art URL from include.boxart
        include = data.get("include", {})
        boxart = include.get("boxart", {})
        base_url = boxart.get("base_url", {}).get("medium", "")
        boxart_data = boxart.get("data", {})
        
        if game_id and game_id in boxart_data:
            game_boxart = boxart_data[game_id]
            for art in game_boxart:
                if art.get("side") == "front":
                    filename = art.get("filename", "")
                    if base_url and filename:
                        result["cover_image_url"] = base_url + filename
                    break
        
        # Resolve genre IDs to names
        genre_ids = game.get("genres")
        if genre_ids:
            result["genres"] = _resolve_genres(genre_ids, api_key)
        
        return result
        
    except Exception as e:
        logger.error(f"Error fetching metadata for '{name}': {e}")
    
    return None


def _query_screenscraper_for_game(name, credentials, system_id=None):
    """
    Queries ScreenScraper.fr API for a game name and returns the parsed result dict,
    or None if no match was found.
    """
    if not credentials:
        logger.error("ScreenScraper: No credentials provided.")
        return None
        
    devid = credentials.get("devid")
    devpassword = credentials.get("devpassword")
    softname = credentials.get("softname", "rommagic")
    ssid = credentials.get("ssid")
    sspassword = credentials.get("sspassword")
    
    if not devid or not devpassword:
        logger.error("ScreenScraper: devid and devpassword are required.")
        return None
        
    url = "https://api.screenscraper.fr/api2/jeuInfos.php"
    params = {
        "devid": devid,
        "devpassword": devpassword,
        "softname": softname,
        "output": "json",
        "romnom": name
    }
    if system_id is not None:
        params["systemeid"] = str(system_id)
        
    if ssid:
        params["ssid"] = ssid
    if sspassword:
        params["sspassword"] = sspassword
        
    data = _make_api_request(url, params)
    if not data or "response" not in data:
        err_msg = data.get("response", {}).get("errortext") if data else None
        if err_msg:
            logger.error(f"ScreenScraper API error: {err_msg}")
        return None
        
    jeu = data["response"].get("jeu")
    if not jeu:
        return None
        
    # Extract game title (prefer US, then SS or FR, then first)
    game_title = None
    noms_obj = jeu.get("noms", {})
    nom_list = noms_obj.get("nom") if isinstance(noms_obj, dict) else None
    if not nom_list:
        nom_list = noms_obj if isinstance(noms_obj, list) else []
        
    if nom_list:
        for n in nom_list:
            if n.get("region") == "us":
                game_title = n.get("text")
                break
        if not game_title:
            for n in nom_list:
                if n.get("region") == "ss":
                    game_title = n.get("text")
                    break
        if not game_title:
            for n in nom_list:
                if n.get("region") == "fr":
                    game_title = n.get("text")
                    break
        if not game_title:
            game_title = nom_list[0].get("text")
            
    # Extract description / synopsis (prefer EN, then FR, then first)
    description = None
    synopsis_list = jeu.get("synopsis", [])
    if not isinstance(synopsis_list, list):
        synopsis_list = [synopsis_list] if synopsis_list else []
    if synopsis_list:
        for s in synopsis_list:
            if s.get("langue") == "en":
                description = s.get("text")
                break
        if not description:
            for s in synopsis_list:
                if s.get("langue") == "fr":
                    description = s.get("text")
                    break
        if not description:
            description = synopsis_list[0].get("text")
            
    # Extract ESRB / PEGI rating
    esrb_rating = None
    pegi_rating = None
    
    def process_classification(c):
        nonlocal esrb_rating, pegi_rating
        if not isinstance(c, dict):
            return
        c_type = (c.get("type") or "").lower()
        c_text = c.get("text") or c.get("nom") or c.get("valeur")
        if c_type == "esrb":
            esrb_rating = c_text
        elif c_type == "pegi":
            pegi_rating = c_text
            
    classifications = jeu.get("classifications", {})
    if isinstance(classifications, list):
        for c in classifications:
            process_classification(c)
    elif isinstance(classifications, dict):
        classif_list = classifications.get("classification")
        if isinstance(classif_list, list):
            for c in classif_list:
                process_classification(c)
        elif isinstance(classif_list, dict):
            process_classification(classif_list)
        else:
            process_classification(classifications)
            
    final_rating = esrb_rating or pegi_rating
    
    # Extract cover image from media
    medias = jeu.get("medias", [])
    if not isinstance(medias, list):
        medias = [medias] if medias else []
    cover_image_url = None
    
    box_2d_candidates = []
    box_3d_candidates = []
    other_cover_candidates = []
    
    for media in medias:
        if not isinstance(media, dict):
            continue
        m_type = (media.get("type") or "").lower()
        m_url = media.get("url")
        if not m_url:
            continue
        m_region = (media.get("region") or "").lower()
        
        if m_type == "box-2d":
            box_2d_candidates.append((m_region, m_url))
        elif m_type == "box-3d":
            box_3d_candidates.append((m_region, m_url))
        elif "cover" in m_type or "box" in m_type:
            other_cover_candidates.append((m_region, m_url))
            
    def select_best(candidates):
        for r in ['us', 'ss', 'eu', 'fr']:
            for cand_region, cand_url in candidates:
                if cand_region == r:
                    return cand_url
        if candidates:
            return candidates[0][1]
        return None
        
    cover_image_url = select_best(box_2d_candidates)
    if not cover_image_url:
        cover_image_url = select_best(box_3d_candidates)
    if not cover_image_url:
        cover_image_url = select_best(other_cover_candidates)
    if not cover_image_url and medias:
        for media in medias:
            if isinstance(media, dict) and (media.get("type") or "").lower() == "screenshot":
                cover_image_url = media.get("url")
                break
                
    # Resolve genres list
    genres_obj = jeu.get("genres", {})
    genre_list = genres_obj.get("genre") if isinstance(genres_obj, dict) else None
    if not genre_list:
        genre_list = genres_obj if isinstance(genres_obj, list) else []
    if not isinstance(genre_list, list):
        genre_list = [genre_list]
        
    resolved_genres = []
    for g in genre_list:
        if not isinstance(g, dict):
            continue
        g_noms = g.get("noms", {})
        g_nom_list = g_noms.get("nom") if isinstance(g_noms, dict) else None
        if not g_nom_list:
            g_nom_list = g_noms if isinstance(g_noms, list) else []
        if not isinstance(g_nom_list, list):
            g_nom_list = [g_nom_list]
            
        genre_name = None
        for gn in g_nom_list:
            if isinstance(gn, dict) and gn.get("langue") == "en":
                genre_name = gn.get("text")
                break
        if not genre_name:
            for gn in g_nom_list:
                if isinstance(gn, dict) and gn.get("langue") == "fr":
                    genre_name = gn.get("text")
                    break
        if not genre_name and g_nom_list and isinstance(g_nom_list[0], dict):
            genre_name = g_nom_list[0].get("text")
        if genre_name:
            resolved_genres.append(genre_name)
            
    genres = ", ".join(resolved_genres) if resolved_genres else None
    
    return {
        "game_title": game_title,
        "description": description,
        "esrb_rating": final_rating,
        "cover_image_url": cover_image_url,
        "genres": genres
    }


def scrape_game_metadata(query_term, api_key=None, is_keyword=False, platform_name=None, provider='thegamesdb', credentials=None):
    """
    Queries the selected scraper API (TheGamesDB or ScreenScraper) for extended game metadata.
    Returns a dict with keys: game_title, cover_image_url, esrb_rating, genres, description.
    Returns None if no results found or credentials/API key are missing.
    """
    if provider == 'screenscraper':
        # ScreenScraper matches best against the original filename with spaces, parentheses, brackets, etc.
        if is_keyword:
            cleaned_name = query_term.replace('_', ' ').replace('-', ' ').strip() if query_term else ""
            cleaned_name = re.sub(r'\s+', ' ', cleaned_name)
        else:
            # Keep original spaces/parentheses/brackets. Just replace underscores with spaces.
            cleaned_name = query_term.replace('_', ' ').strip() if query_term else ""
            cleaned_name = re.sub(r'\s+', ' ', cleaned_name)
            
        if not cleaned_name:
            return None
            
        system_id = SCREENSCRAPER_SYSTEM_IDS.get(platform_name)
        result = _query_screenscraper_for_game(cleaned_name, credentials, system_id=system_id)
        if result and result.get("game_title"):
            return result
            
        # Fallback: progressively trim words from the end (only for filename searches)
        # For fallback, we clean brackets/parentheses so we can trim the base title
        if not is_keyword:
            cleaned_base = clean_filename(query_term)
            for trimmed_query in _generate_trimmed_queries(cleaned_base):
                logger.info(f"ScreenScraper fallback: retrying with trimmed query '{trimmed_query}'")
                result = _query_screenscraper_for_game(trimmed_query, credentials, system_id=system_id)
                if result and result.get("game_title"):
                    return result
        return None

    # Default to thegamesdb
    if is_keyword:
        # Clean underscores, dashes, and duplicate spaces from user-entered keywords
        cleaned_name = query_term.replace('_', ' ').replace('-', ' ').strip() if query_term else ""
        cleaned_name = re.sub(r'\s+', ' ', cleaned_name)
    else:
        cleaned_name = clean_filename(query_term)
        
    if not cleaned_name:
        return None

    # Default to thegamesdb
    if not api_key:
        return None
        
    # Resolve platform name to TheGamesDB platform ID for filtering
    platform_id = _fetch_platform_id(platform_name, api_key) if platform_name else None
    if platform_name and platform_id:
        logger.info(f"Scraper: filtering results to platform '{platform_name}' (ID: {platform_id})")
    elif platform_name:
        logger.info(f"Scraper: could not resolve platform '{platform_name}' to a TheGamesDB ID, searching without filter")
    
    # Try the full cleaned name first
    result = _query_api_for_game(cleaned_name, api_key, platform_id=platform_id)
    if result and result.get("game_title"):
        return result
    
    # Fallback: progressively trim words from the end (only for filename searches)
    if not is_keyword:
        for trimmed_query in _generate_trimmed_queries(cleaned_name):
            logger.info(f"Scraper fallback: retrying with trimmed query '{trimmed_query}'")
            result = _query_api_for_game(trimmed_query, api_key, platform_id=platform_id)
            if result and result.get("game_title"):
                return result
    
    return None


def scrape_game_title(query_term, api_key=None, is_keyword=False, platform_name=None, provider='thegamesdb', credentials=None):
    """
    Backward-compatible wrapper that returns only the game title string.
    """
    metadata = scrape_game_metadata(
        query_term, api_key=api_key, is_keyword=is_keyword,
        platform_name=platform_name, provider=provider, credentials=credentials
    )
    if metadata:
        return metadata.get("game_title")
    return None
