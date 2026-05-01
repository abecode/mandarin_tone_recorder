import random
import pandas as pd


class StimulusManager:
    def __init__(self, csv_path):
        self.df = pd.read_csv(csv_path).fillna("")
        if "stimulus_id" not in self.df.columns:
            raise ValueError("CSV must contain a stimulus_id column.")
        self.order = list(self.df.index)
        random.shuffle(self.order)
        self.position = 0

    def next_stimulus(self):
        if self.position >= len(self.order):
            random.shuffle(self.order)
            self.position = 0

        row = self.df.iloc[self.order[self.position]].to_dict()
        self.position += 1
        return row
