import json
from pathlib import Path

def find_data_file(filename_name: str) -> Path:
    """Locate the data file dynamically, checking parent and grand-parent directories."""
    # 1. Try checking target_bot/data/filename (if data_loader is in src/)
    path1 = Path(__file__).parent.parent / "data" / filename_name
    if path1.exists():
        return path1
        
    # 2. Try checking target_bot/data/filename (if data_loader is in a nested helper folder)
    path2 = Path(__file__).parent.parent.parent / "data" / filename_name
    if path2.exists():
        return path2
        
    # 3. Fallback to path1
    return path1

def load_items():
    """Load items from data/item_urls.json"""
    filename = find_data_file("item_urls.json")

    try:
        with open(filename, 'r') as file:
            item_ids = [str(item) for item in json.load(file)]
            return item_ids
    except FileNotFoundError:
        print(f"Error: {filename} not found.")
    except json.JSONDecodeError:
        print(f"Error: {filename} contains invalid JSON.")
    return []

def load_stores():
    """Load stores from data/stores.json"""
    filename = find_data_file("stores.json")
    try:
        with open(filename, 'r') as f:
            return json.load(f)['stores']
    except FileNotFoundError:
        print(f"Error: {filename} not found.")
    return []

def load_previous_session():
    """Load previous_session.json"""
    filename = find_data_file("previous_session.json")
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: {filename} not found.")
    except json.JSONDecodeError:
        pass
    return {}