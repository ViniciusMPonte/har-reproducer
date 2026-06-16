import subprocess
import urllib.parse
import base64
from pathlib import Path
from typing import Optional, Tuple

def grep_in_real_responses(responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:
    """
    Searches for a pattern in all res_*.json files within the responses_dir.
    Returns the first match as (step_index, content) or None if not found.
    
    The search is performed using the system grep for efficiency.
    """
    try:
        # -F: Fixed strings, -r: recursive, -n: line number, -m 1: max 1 match
        # Using -l instead of -n to get the filename first, then we parse the filename for the index.
        cmd = ["grep", "-rl", "--include=res_*.json", pattern, str(responses_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        if not result.stdout:
            return None
            
        # Get the first matching file
        first_match_file = result.stdout.splitlines()[0]
        file_path = Path(first_match_file)
        
        # Extract index from res_NNNN.json
        filename = file_path.name
        try:
            # res_0001.json -> 1
            index_str = filename.split('_')[1].split('.')[0]
            step_index = int(index_str)
        except (IndexError, ValueError):
            return None
            
        return step_index, filename

    except subprocess.CalledProcessError:
        return None

def try_decode(value: str) -> str:
    """
    Attempts to decode a value through a sequence: Literal -> URL-decoded -> Base64-decoded.
    Returns the most 'decoded' version that looks like a string.
    """
    # 1. Literal
    current = value
    
    # 2. URL-decoded
    decoded_url = urllib.parse.unquote(current)
    if decoded_url != current:
        current = decoded_url
        
    # 3. Base64-decoded
    try:
        # Try to decode as base64. We only accept it if it results in valid UTF-8.
        # Base64 strings usually have specific chars; we check if it's possible.
        b64_bytes = base64.b64decode(current, validate=True)
        decoded_b64 = b64_bytes.decode("utf-8")
        # Basic heuristic: if it contains non-printable chars, it might not be a token string.
        if decoded_b64.isprintable():
            current = decoded_b64
    except Exception:
        pass
        
    return current
