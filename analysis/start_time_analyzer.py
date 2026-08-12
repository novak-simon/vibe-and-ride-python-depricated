from analysis.model import AudioAnalysis

def analyze_for_start_time(librosa_analysis: AudioAnalysis, beatnet_analysis: AudioAnalysis) -> int:
    """
    Estimates best starting time in miliseconds for playing the song
    Calculates based on audio analysis from Librosa and Beatnet
    TEMPORARILY RETURNS ALWAYS ZERO
    """
    return 10000