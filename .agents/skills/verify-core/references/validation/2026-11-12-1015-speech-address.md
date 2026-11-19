# verify-core: speech-address

## 2026-11-12 speech-address: speech channels with the room detail (Spark)

Branch `speech-address` from `06be6921`, the trial service `slop-trials-stdb`. `speech.py channels`, `core-sa-11121008-channels`: 31 PASS, 0 FAIL. Unit test `a_line_to_the_room_says_whom_it_calls_and_whom_its_speaker_talks_with` covers the word forms, `{how}` placement and `chronicle_way`.

The first run (`core-sa-11121005-channels`) failed "call: d, 20 m away, hears it, and how far". d read "A stranger calls out from about 20 m to the room while talking with a stranger": the speaker's earlier whisper to b counted as a conversation, and the detail came after the distance. Two fixes followed:

- a private way's line (`only_to`) no longer counts as a conversation;
- the shipped `call` template places the detail at `{how}` ("{a} calls out{how} from about {d} m").

After merging main `d80a1373`, `core-sam-11121029-channels` failed one check: "call: a second within 6 s is refused". The second call came 9.5 s after the first at load average ~34, so the call was rightly accepted; this was harness timing, not the change. The rerun, `core-sam2-11121034-channels`, passed 31/31.
