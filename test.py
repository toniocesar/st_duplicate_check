from st_copy import copy_button
import streamlit as st

msg = 'some dsdcdcs message'
st.warning(msg)

copy_button(
    msg,
    icon='st',  # default, use 'st' as alternative
    tooltip='Copy Text',  # defaults to 'Copy'
    copied_label='Custom "Copied!" text',  # defaults to 'Copied!'
    key='Any key',  # If omitted, a random key will be generated
)