import gradio as gr
import mandarin_tone_recorder as mtr

from mandarin_tone_recorder.config import (
    STIMULI_CSV,
    AUDIO_DIR,
    METADATA_CSV,
    MIN_DURATION_SEC,
    MAX_DURATION_SEC,
    CLIPPING_THRESHOLD,
    SILENCE_RMS_THRESHOLD,
)

from mandarin_tone_recorder.stimuli import StimulusManager
from mandarin_tone_recorder.quality import analyze_audio
from mandarin_tone_recorder.storage import save_recording


stimuli = StimulusManager(STIMULI_CSV)


def format_prompt(stimulus):
    pinyin = stimulus.get("pinyin", "")
    ascii_form = stimulus.get("ascii", "")
    tone = stimulus.get("tone", "")
    ipa = stimulus.get("ipa", "")
    attested = stimulus.get("is_attested", "")

    return f"""
# Please say: **{pinyin}**

- Pinyin with tone number: **{ascii_form}{tone}**
- IPA: `/{ipa}/`
- Attested Mandarin syllable-tone combination: **{attested}**

Chinese terms:
- 音节 *yīnjié* = syllable
- 声调 *shēngdiào* = tone
"""


def get_next_prompt():
    stimulus = stimuli.next_stimulus()
    return (
        stimulus,                 # stimulus_state
        format_prompt(stimulus),   # prompt_md
        None,                     # audio_input: clear old recording
        {},                       # quality_state: clear old quality result
        "",                       # quality_report
        "",                       # save_report
    )


def check_quality(audio):
    result = analyze_audio(
        audio,
        min_duration_sec=MIN_DURATION_SEC,
        max_duration_sec=MAX_DURATION_SEC,
        clipping_threshold=CLIPPING_THRESHOLD,
        silence_rms_threshold=SILENCE_RMS_THRESHOLD,
    )

    lines = [
        f"Quality pass: **{result.get('quality_pass')}**",
        f"Reason: {result.get('reason')}",
    ]

    if "duration_sec" in result:
        lines.extend([
            f"Duration: {result['duration_sec']} sec",
            f"RMS: {result['rms']}",
            f"Peak amplitude: {result['peak_amplitude']}",
            f"Clipping ratio: {result['clipping_ratio']}",
        ])

    return result, "\n\n".join(lines)


def accept_recording(
    audio,
    stimulus,
    quality,
    participant_id,
    session_id,
    speaker_type,
    mandarin_background,
):
    if audio is None:
        return "No audio recorded yet."

    if not stimulus:
        return "No stimulus selected."

    if not quality:
        return "Please run quality check first."

    participant = {
        "participant_id": participant_id,
        "session_id": session_id,
        "speaker_type": speaker_type,
        "mandarin_background": mandarin_background,
    }

    recording_id, audio_path = save_recording(
        audio_tuple=audio,
        stimulus=stimulus,
        participant=participant,
        quality=quality,
        audio_dir=AUDIO_DIR,
        metadata_csv=METADATA_CSV,
    )

    return f"Saved recording `{recording_id}` to `{audio_path}`."


with gr.Blocks(title="Mandarin Tone Recording Prototype") as demo:
    gr.Markdown(
        """
# Mandarin Tone Recording Prototype

This prototype collects isolated Mandarin **音节** *yīnjié* “syllables” with **声调** *shēngdiào* “tones”.

Workflow:

1. Enter participant/session metadata.
2. Click **Next stimulus**.
3. Record the prompted syllable.
4. Check quality.
5. Accept/save or retry.
"""
    )

    stimulus_state = gr.State({})
    quality_state = gr.State({})

    with gr.Row():
        participant_id = gr.Textbox(label="Participant ID", value="p001")
        session_id = gr.Textbox(label="Session ID", value="s001")

    with gr.Row():
        speaker_type = gr.Dropdown(
            label="Speaker type",
            choices=["native", "heritage", "learner", "other"],
            value="learner",
        )
        mandarin_background = gr.Textbox(
            label="Mandarin background",
            placeholder="e.g., L2 learner, 2 years study; native Beijing speaker; heritage speaker",
        )

    prompt_md = gr.Markdown("Click **Next stimulus** to begin.")

    next_button = gr.Button("Next stimulus")

    audio_input = gr.Audio(
        label="Record syllable",
        sources=["microphone"],
        type="numpy",
    )

    with gr.Row():
        check_button = gr.Button("Check quality")
        accept_button = gr.Button("Accept and save")
        retry_button = gr.Button("Retry / clear")

    quality_report = gr.Markdown()
    save_report = gr.Markdown()

    next_button.click(
        fn=get_next_prompt,
        outputs=[
            stimulus_state,
            prompt_md,
            audio_input,
            quality_state,
            quality_report,
            save_report,
        ],
    )

    check_button.click(
        fn=check_quality,
        inputs=[audio_input],
        outputs=[quality_state, quality_report],
    )

    accept_button.click(
        fn=accept_recording,
        inputs=[
            audio_input,
            stimulus_state,
            quality_state,
            participant_id,
            session_id,
            speaker_type,
            mandarin_background,
        ],
        outputs=[save_report],
    )

    retry_button.click(
        fn=lambda: (None, {}, "", ""),
        outputs=[audio_input, quality_state, quality_report, save_report],
    )


if __name__ == "__main__":
    demo.launch()
