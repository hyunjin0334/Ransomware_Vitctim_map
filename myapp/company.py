import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import certifi


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_JSON_PATH = BASE_DIR / "myapp" / "static" / "myapp" / "company_locations.json"
CACHE_JSON_PATH = BASE_DIR / "myapp" / "cached_victims.json"

API_BASE = "https://api.ransomware.live/v2"

# Data source options
USE_GROUP_ENDPOINT = False
GROUP_NAME = "lockbit5"
RECENT_LIMIT = 30

# Geocoding
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

HEADERS = {
    "User-Agent": "RansomwareVictimMap/1.0 (educational project)"
}

VERIFY_CERT_PATH = certifi.where()
REQUEST_TIMEOUT = 60
GEOCODING_DELAY_SECONDS = 1.1

# Retry settings
API_RETRY_COUNT = 3
API_RETRY_DELAY_SECONDS = 5

# Optional fallback data for development/demo
USE_FALLBACK_IF_API_FAILS = True
FALLBACK_VICTIMS = [
    {
        "victim": "Samsung Electronics",
        "group": "demo",
        "country": "KR",
        "attackdate": "2026-01-10"
    },
    {
        "victim": "Google",
        "group": "demo",
        "country": "US",
        "attackdate": "2026-01-12"
    },
    {
        "victim": "Microsoft",
        "group": "demo",
        "country": "US",
        "attackdate": "2026-01-15"
    },
    {
        "victim": "Amazon",
        "group": "demo",
        "country": "US",
        "attackdate": "2026-01-18"
    },
    {
        "victim": "Tesla",
        "group": "demo",
        "country": "US",
        "attackdate": "2026-01-20"
    }
]


def build_api_url() -> str:
    if USE_GROUP_ENDPOINT:
        return f"{API_BASE}/groupvictims/{GROUP_NAME}"
    return f"{API_BASE}/recentvictims"


def save_cached_victims(data: List[Dict[str, Any]]) -> None:
    try:
        CACHE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"Saved API cache to: {CACHE_JSON_PATH}")
    except Exception as e:
        print(f"Failed to save cache: {e}")


def load_cached_victims() -> List[Dict[str, Any]]:
    try:
        if not CACHE_JSON_PATH.exists():
            return []

        with open(CACHE_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            print(f"Loaded cached victim data: {len(data)} records")
            return data

        return []
    except Exception as e:
        print(f"Failed to load cache: {e}")
        return []


def fetch_victims_with_retry() -> List[Dict[str, Any]]:
    url = build_api_url()

    for attempt in range(1, API_RETRY_COUNT + 1):
        try:
            print(f"Fetching victim data... attempt {attempt}/{API_RETRY_COUNT}")
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                verify=VERIFY_CERT_PATH
            )
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, list):
                print("Unexpected API response format. Expected a list.")
                return []

            if not USE_GROUP_ENDPOINT and RECENT_LIMIT > 0:
                data = data[:RECENT_LIMIT]

            save_cached_victims(data)
            return data

        except Exception as e:
            print(f"Attempt {attempt} failed: {e}")

            if attempt < API_RETRY_COUNT:
                print(f"Retrying in {API_RETRY_DELAY_SECONDS} seconds...")
                time.sleep(API_RETRY_DELAY_SECONDS)

    print("All API attempts failed.")
    return []


def normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    return text


def normalize_victim_name(item: Dict[str, Any]) -> Optional[str]:
    candidates = [
        item.get("victim"),
        item.get("name"),
        item.get("domain"),
        item.get("website"),
        item.get("post_title"),
        item.get("title"),
    ]

    for value in candidates:
        normalized = normalize_text(value)
        if normalized:
            return normalized

    return None


def normalize_country(item: Dict[str, Any]) -> str:
    candidates = [
        item.get("country"),
        item.get("country_code"),
        item.get("location"),
    ]

    for value in candidates:
        normalized = normalize_text(value)
        if normalized:
            return normalized.upper()

    return "N/A"


def normalize_group(item: Dict[str, Any]) -> str:
    candidates = [
        item.get("group"),
        GROUP_NAME if USE_GROUP_ENDPOINT else None
    ]

    for value in candidates:
        normalized = normalize_text(value)
        if normalized:
            return normalized

    return "N/A"


def normalize_attack_date(item: Dict[str, Any]) -> str:
    candidates = [
        item.get("attackdate"),
        item.get("discovered"),
        item.get("date"),
        item.get("published"),
    ]

    for value in candidates:
        normalized = normalize_text(value)
        if normalized:
            return normalized

    return "N/A"


def is_valid_company_name(name: str) -> bool:
    if not name:
        return False

    normalized = name.strip()
    if len(normalized) < 3:
        return False

    lowered = normalized.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return False

    parts = lowered.split(".")
    if len(parts) >= 2:
        return False

    return True


def build_geocoding_query(company: str, country: str) -> str:
    if country != "N/A":
        return f"{company}, {country}"
    return company


def geocode_company(company: str, country: str = "N/A") -> Tuple[Optional[float], Optional[float]]:
    query = build_geocoding_query(company, country)

    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
    }

    try:
        response = requests.get(
            NOMINATIM_URL,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=VERIFY_CERT_PATH
        )
        response.raise_for_status()
        results = response.json()

        if not isinstance(results, list) or not results:
            return None, None

        lat = float(results[0]["lat"])
        lon = float(results[0]["lon"])
        return lat, lon

    except Exception as e:
        print(f"Geocoding failed for '{company}': {e}")
        return None, None


def deduplicate_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output = []

    for record in records:
        key = (
            record.get("company"),
            record.get("group"),
            record.get("country"),
            record.get("attackdate"),
            record.get("status"),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(record)

    return output


def build_output_records(victims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records = []

    success_count = 0
    fail_count = 0
    skip_count = 0

    for idx, item in enumerate(victims, start=1):
        company = normalize_victim_name(item)
        group = normalize_group(item)
        country = normalize_country(item)
        attack_date = normalize_attack_date(item)

        if not company or not is_valid_company_name(company):
            skip_count += 1

            records.append({
                "company": company if company else "N/A",
                "latitude": None,
                "longitude": None,
                "phonenumber": "N/A",
                "group": group,
                "country": country,
                "attackdate": attack_date,
                "source": "ransomware.live",
                "status": "skipped_invalid_name"
            })

            print(f"{idx}: skipped (invalid name) -> {company}")
            continue

        lat, lon = geocode_company(company, country)

        if lat is None or lon is None:
            fail_count += 1

            records.append({
                "company": company,
                "latitude": None,
                "longitude": None,
                "phonenumber": "N/A",
                "group": group,
                "country": country,
                "attackdate": attack_date,
                "source": "ransomware.live",
                "status": "geocoding_failed"
            })

            print(f"{idx}: geocoding failed -> {company}")
            time.sleep(GEOCODING_DELAY_SECONDS)
            continue

        success_count += 1

        records.append({
            "company": company,
            "latitude": lat,
            "longitude": lon,
            "phonenumber": "N/A",
            "group": group,
            "country": country,
            "attackdate": attack_date,
            "source": "ransomware.live",
            "status": "success"
        })

        print(f"{idx}: {company} -> ({lat}, {lon}) [{group} / {country}]")
        time.sleep(GEOCODING_DELAY_SECONDS)

    records = deduplicate_records(records)

    print("\n===== SUMMARY =====")
    print(f"Total input: {len(victims)}")
    print(f"Success: {success_count}")
    print(f"Geocoding failed: {fail_count}")
    print(f"Skipped (invalid): {skip_count}")
    print(f"Final JSON records: {len(records)}")

    return records


def save_json(data: List[Dict[str, Any]]) -> None:
    OUTPUT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"Saved to: {OUTPUT_JSON_PATH}")


def main() -> None:
    victims = fetch_victims_with_retry()

    if not victims:
        cached_victims = load_cached_victims()
        if cached_victims:
            print("Using cached victim data.")
            victims = cached_victims

    if not victims and USE_FALLBACK_IF_API_FAILS:
        print("Using fallback victim data.")
        victims = FALLBACK_VICTIMS

    if not victims:
        print("No victim data available. Writing empty JSON.")
        save_json([])
        return

    print(f"Fetched victim records: {len(victims)}")

    final_data = build_output_records(victims)
    save_json(final_data)


if __name__ == "__main__":
    main()