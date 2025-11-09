# camera_stub.py
def get_camera_state():
    return {
        "instrument_state": "trumpet",
        "camera_state": "play",
        "recording": False,           # don't trigger count-in mute
        "is_note_being_played": True, # hold a note while /dist moves
    }