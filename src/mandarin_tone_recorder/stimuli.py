"""Stimulus loading and ordering utilities.

This module owns the details of reading the stimulus CSV and presenting
stimuli to the application. It deliberately does not depend on FastAPI,
Gradio, Django, or any other web framework, so it can be reused from
different frontends if necessary
"""

import random
from pathlib import Path
from typing import Any

import pandas as pd


class StimulusManager:
    """Load, shuffle, and retrieve Mandarin tone recording stimuli.

    The stimulus CSV is expected to contain one row per stimulus. At minimum,
    it must contain a ``stimulus_id`` column. Other columns such as ``pinyin``,
    ``ascii``, ``tone``, ``ipa``, ``onset``, ``nucleus``, etc. are preserved and
    returned as dictionaries.

    Parameters
    ----------
    csv_path:
        Path to the CSV file containing the stimulus inventory.

    Attributes
    ----------
    df:
        The loaded stimulus table as a pandas DataFrame.
    order:
        A shuffled list of row indices used by ``next_stimulus``.
    position:
        The current position in the shuffled order.
    """
    
    def __init__(self, csv_path: str | Path):
        """Create a stimulus manager from a CSV file.

        Parameters
        ----------
        csv_path:
            Path to the stimulus CSV.

        Raises
        ------
        ValueError
            If the CSV does not contain a ``stimulus_id`` column.
        """
        self.csv_path = Path(csv_path)
        self.df = pd.read_csv(self.csv_path).fillna("")

        if "stimulus_id" not in self.df.columns:
            raise ValueError("CSV must contain a stimulus_id column.")

        self.order = list(self.df.index)
        random.shuffle(self.order)
        self.position = 0

    def next_stimulus(self) -> dict[str, Any]:
        """Return the next stimulus in a shuffled order.

        When all stimuli have been returned once, the order is reshuffled and
        iteration starts again. This method is useful for older one-stimulus-at-
        a-time workflows, such as the original Gradio prototype.

        Returns
        -------
        dict[str, Any]
            A dictionary representing one stimulus row.
        """
        if self.position >= len(self.order):
            random.shuffle(self.order)
            self.position = 0

        row = self.df.iloc[self.order[self.position]].to_dict()
        self.position += 1
        return row

    def all_stimuli(
        self,
        *,
        shuffle: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return a list of stimuli for one recording session.

        This is the method used by the browser-based recorder. The frontend
        receives the full list of stimuli at page load, then advances through
        them locally with the Start/Next buttons.

        Parameters
        ----------
        shuffle:
            Whether to randomize the order before returning the list.
        limit:
            Optional maximum number of stimuli to return. This is useful for
            quick debugging sessions.

        Returns
        -------
        list[dict[str, Any]]
            A list of stimulus row dictionaries.
        """
        indices = list(self.df.index)

        if shuffle:
            random.shuffle(indices)

        if limit is not None:
            indices = indices[:limit]

        return [self.df.iloc[i].to_dict() for i in indices]

    def by_id(self, stimulus_id: str) -> dict[str, Any] | None:
        """Look up a stimulus by its stable stimulus ID.

        The upload endpoint uses this method to verify that a browser upload
        refers to a real stimulus and to recover the full stimulus metadata
        before writing the recording metadata row.

        Parameters
        ----------
        stimulus_id:
            The value from the ``stimulus_id`` column.

        Returns
        -------
        dict[str, Any] | None
            The matching stimulus row as a dictionary, or ``None`` if no match
            exists.
        """
        matches = self.df[self.df["stimulus_id"].astype(str) == str(stimulus_id)]

        if matches.empty:
            return None

        return matches.iloc[0].to_dict()

