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
            


        print(values_10)

        values_blocks = []
        for j in range(len(values_10)):
            if not temp:
                temp.add(values_10[j])
                continue
            avg = mean([val[0] for val in temp])
            if abs(values_10[j][0] - avg) < 20:
                temp.add(values_10[j])
            else:
                values_blocks.append((round(mean([val[0] for val in temp])), round(j*length_10, 1)))
                temp.clear()
        print(values_blocks)

        for val in values_blocks:
            if val[0] < 10:
                continue
            return val[1]        
        return 0