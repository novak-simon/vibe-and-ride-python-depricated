from statistics import mean
from music.model import Song

class StartTimeAnalyzer:

    def analyze(self, song: Song) -> float:
        """
        Estimates best starting time in miliseconds for playing the song
        Calculates based on waveforms of the song
        """
        if not song.waveform:
            return 0

        # Groups waveforms into groups of 10 (approximately 2 seconds) and for each group takes the average waveform
        values_10 = []
        temp = set()
        i = 0
        waveforms = len(song.waveform)
        length_10 = song.duration/waveforms*10
        print(f"Length 10: {length_10}")
        for val in song.waveform:
            i += 1
            temp.add(val)
            if i % 10 == 0 or i == waveforms-1:
                values_10.append((round(mean(temp)), round(length_10/10*i, 1)))
                temp.clear()
            
        # Goes through grouped values and compares each value to the average of the current forming group, when too distinct, adds current forming group to new list and starts forming new group
        values_blocks = []
        for j in range(len(values_10)):
            if not temp:
                temp.add(values_10[j])
                continue
            avg = mean([val[0] for val in temp])
            if abs(values_10[j][0] - avg) < 15:
                temp.add(values_10[j])
            else:
                values_blocks.append((round(mean([val[0] for val in temp])), round(j*length_10, 1)))
                temp.clear()

        # Takes the first block that is <60 and isn't the begining silence (defined as <10) also checks if it isn't too far in the song
        alt_val = None
        for val in values_blocks:
            if val[0] < 10:
                alt_val = val
                continue
            elif song.duration / val[1] < 2 or val[0] > 60:
                if alt_val:
                    return alt_val[1]
                return 0
            return val[1]        
        return 0