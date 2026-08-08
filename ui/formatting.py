def format_seconds(seconds: float) -> str:
    total_seconds = int(round(max(0.0, seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02}:{secs:02}"
    return f"{minutes:02}:{secs:02}"