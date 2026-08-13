from music.model import Song

class StartTimeAnalyzer:

    def analyze(self, song: Song) -> int:
        """
        Estimates best starting time in miliseconds for playing the song
        Calculates based on waveforms of the song
        TEMPORARILY RETURNS ALWAYS ZERO
        """
        if not song.waveform:
            return 0
        
        
        return 0