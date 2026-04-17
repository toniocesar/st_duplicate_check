#!/usr/bin/env python
# coding: utf-8

from bs4 import BeautifulSoup
import requests
import json
from datetime import datetime, timedelta
import pandas as pd
import re
from pprint import pprint
from flask import Flask, request
from rapidfuzz import fuzz, process
from fuzzysearch import find_near_matches
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import os
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx
from numpy.random import default_rng as rng


### Variable Declarations

if "duplicate_leis" not in st.session_state:
    st.session_state.duplicate_leis = []
    duplicate_leis = st.session_state.duplicate_leis

if "all_gleif_duplicates" not in st.session_state:
    st.session_state.all_gleif_duplicates = []
    all_gleif_duplicates = st.session_state.all_gleif_duplicates

if "all_results" not in st.session_state:
    st.session_state.all_results = []
    all_results = st.session_state.all_results

if "gleif_variables" not in st.session_state:
    st.session_state.gleif_variables = {}
    gleif_variables = st.session_state.gleif_variables

if "manager_vars" not in st.session_state:
    st.session_state.manager_vars = {}
    manager_vars = st.session_state.manager_vars

if "lei_status_pairs" not in st.session_state:
    st.session_state.lei_status_pairs = {}
    lei_status_pairs = st.session_state.lei_status_pairs

if "missing_leis_count" not in st.session_state:
    st.session_state.missing_leis_count = None
    missing_leis_count = st.session_state.missing_leis_count

if "was_a_lei_skipped" not in st.session_state:
    st.session_state.was_a_lei_skipped = False
    was_a_lei_skipped = st.session_state.was_a_lei_skipped

if "skipped_leis" not in st.session_state:
    st.session_state.skipped_leis = []
    skipped_leis = st.session_state.skipped_leis


# Sidebar Configuration
with st.sidebar:
    # Logo
    st.image("images/lei-manager-logo.png")
    
    st.markdown("---")
    
    # Description
    st.subheader("About")
    st.markdown("""
    **LEI Duplicate Checker** is a tool designed to identify and analyze potential duplicate LEI (Legal Entity Identifier) records.
    """)
    
    st.markdown("<p style='text-align: center; font-size: 0.75rem; color: gray;'>For EQS employees use only</p>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Help Section
    if st.button("❓ Help", use_container_width=True):
        st.markdown("""
        ### How it works
        The application compares candidates from a duplicates message against LEI Manager data, using fuzzy matching to evaluate similarities across multiple features, like Registration ID, Legal Name, Address...
                    
        ### How to Use
                    
        1. **Process Duplicates**: Paste the duplicates message that pops up on the top right of the LEI Manager
        2. **Process LEI Manager**: Paste the full text from the LEI Manager for the company you're checking against
        3. **Check Duplicates**: Click to run the comparison and view results
        
        ### Results Interpretation
        
        - **🔴 RED**: Likely duplicate, high similarity detected
        - **🟡 YELLOW**: Possible duplicate, moderate similarity or authority mismatch
        - **🟢 GREEN**: Unlikely duplicate, low similarity
        
        ### Scoring
        
        - Scores range from 0-100. Values close to 100 indicate high similarity
        - Date-scores are shown as the difference in days. Lower values indicate higher similarity.
        
        ### FAQ
         
        - Make sure to **follow the steps in order**: first process duplicates, then process LEI Manager, and only then check duplicates. This is important to ensure all variables are properly set.
        - The **Different Authority ID (⚠️)** warning calls for manual review, since the registration numbers from 2 different authorities cannot be compared directly.
        - The status displayed for each LEI (eg ISSUED, PENDING_VALIDATION) is based on the information extracted from the duplicates message. It does **not** represent the current state of the LEI in the GLEIF database.
        - For companies based in Germany, the **Different Authority ID (⚠️)** warning will not be displayed, since all German companies are registered under the same authority (Handelsregister), but with different authority IDs. In other words, german Registration IDs can be compared with each other, regardless of the authority it was issued in.
                    
                    
        """)
    
    st.markdown("---")
    
    # Author Credit
    st.markdown("""
    <div style="text-align: center; font-size: 0.8rem; color: gray; margin-top: 2rem;">
    <p><strong>LEI Duplicate Checker</strong></p>
    <p>EQS LEI Team (2026)</p>
    </div>
    """, unsafe_allow_html=True)


pattern = r'^[A-Z0-9]{20}$'
pattern_lei_status = r'([A-Z0-9]{20})\n.+?\n.+?\n(ISSUED|PENDING_VALIDATION|LAPSED)'
pattern_duplicate_count = r'(\d+)\s+duplicate\(s\)\s+found'
url_stem = "https://api.gleif.org/api/v1/lei-records/"

def handle_GST_PAN_reg_ID(gleif_reg_ID: str, manager_reg_ID: str, current_score: float) -> float   :
    """
    Custom handling for GST/PAN Registration IDs (specific to RA000754 - India).
    Since the PAN number is embedded within the GSTRegistration ID and is a critical identifier,
    we must consider this test
    """
    pan_score = fuzz.ratio(gleif_reg_ID[2:-3], manager_reg_ID[2:-3]) if gleif_reg_ID and manager_reg_ID else None
    return max(current_score, pan_score) if pan_score is not None else current_score

def handle_no_authority_check() -> float:
    """
    For cases like Germany, where all reg_IDs are issued by the same
    authority, but with different authority IDs.

    In other words, all numbers are registered at HAndelsregister, but
    are often different (eg Amt Hamburg has different ID than Berlin)
    """
    return 100.0

FEATURE_KEY_MAP = {
    "Authority ID": "authority_ID",
    "Registration ID": "reg_ID",
    "Legal Name": "legal_name",
    "Address": "address",
    "ZIP Code": "zipcode",
    "Creation Date": "date",   # usado só para exibição
    "Legal Form": "legal_form"
}

AUTHORITY_HANDLERS = {
    "RA000754": handle_GST_PAN_reg_ID,
}

JURISDICTION_HANDLERS = {
    "DE": {
        "function": handle_no_authority_check,
        "message": "Authority mismatch warning (⚠️) will **not** be displayed for companies based in **Germany**. See FAQ more more details.",
        "severity": "info"
    }
}

SCORE_THRESHOLDS = {
    "Registration ID": {"RED": 95,
                        "YELLOW": 90},
    "Address": {"RED": 80,
                "YELLOW": 65},
    "ZIP Code": {"RED": 95, # Importante: o ZIP code vai ficar vermelho na tabela, mas na funcao que gera os emojis coloridos, o zip code vai ficar no maximo amarelo, e nao mais vermelho.
                "YELLOW": 90},
    "Creation Date": {"RED": 1,
                      "YELLOW": 7},
    
    
}


# Reading of dictionaries

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Functions

@st.cache_data
def load_gleif_authority():
    return pd.read_csv(
        os.path.join(DATA_DIR, "GLEIF_authority_dictionary.csv")
    )

@st.cache_data
def load_legal_form_dictionary():
    return pd.read_excel(
        os.path.join(DATA_DIR, "GLEIF_legal_form_dictionary.xlsx")
    )

@st.cache_data
def load_RAformat_dictionary():
    return pd.read_excel(
        os.path.join(DATA_DIR, "GLEIF_RAformat_dictionary.xlsx")
    )

@st.cache_data
def load_zipcode_dictionary():
    return pd.read_excel(
        os.path.join(DATA_DIR, "zipcode_dictionary.xlsx"),
        sheet_name="RegEx_EQS"
    )

df_legal_form = load_legal_form_dictionary()
df_gleif_authority = load_gleif_authority()
df_RA_format = load_RAformat_dictionary()
df_zipcode = load_zipcode_dictionary()

def fetch_gleif_vars(lei: str):
    """
    Doesn't actually perform a duplicate check, 
    but retrieves all relevant information from GLEIF API for a given LEI, 
    and formats it in a way that can be easily compared to the LEI Manager data.
    
    :param lei: lei code to be checked for duplicates (20-character alphanumeric string)
    :type lei: str

    returns:
    - gleif_variables (dict): dicionário contendo as variáveis extraídas da API
    """
    lei_status_pairs = st.session_state.lei_status_pairs
    gleif_variables = {}
    url = f"{url_stem}{lei}"


    print(f"LEI: {lei_status_pairs.get(lei)}")  # Debug print for LEI status
    page = requests.get(url)
    if page.status_code != 200:
        st.session_state.was_a_lei_skipped = True
        status = lei_status_pairs.get(lei)
        # If 404, check if it's PENDING_VALIDATION
        if page.status_code == 404:
            if status == "PENDING_VALIDATION":
                st.warning(f"Skipping {lei} — {status}")
                # Add to skipped_leis list
                st.session_state.skipped_leis.append({
                    "lei": lei,
                    "status": status,
                    "error_code": page.status_code
                })
                return None
        
        # For all other errors (or 404 without PENDING_VALIDATION), add to skipped list and show error
        st.session_state.skipped_leis.append({
            "lei": lei,
            "status": status,
            "error_code": page.status_code
        })
        print(f"\n\n ********** Error searching for LEI {lei} — status {page.status_code} ********** \n\n")
        st.warning(f"Skipping LEI {lei} — LEI not found ({page.status_code}) \n\n")
        return

    json_data = page.json()

    DEFAULT_DATE = datetime(1, 1, 1)

    # GLEIF Date
    gleif_date = json_data["data"]["attributes"]["entity"]["creationDate"]
    if gleif_date is None:
        gleif_date = DEFAULT_DATE
    else:
        gleif_date = datetime.fromisoformat(gleif_date).replace(tzinfo=None)
    gleif_variables["date"] = gleif_date

    # GLEIF authority ID (RA code of the authority that issued the LEI)
    gleif_authority_ID = json_data["data"]["attributes"]["entity"]["registeredAt"]["id"]
    gleif_variables["authority_ID"] = gleif_authority_ID

    # GLEIF authority local name
    gleif_authority_temp = df_gleif_authority.loc[df_gleif_authority["Registration Authority Code"] == gleif_authority_ID, "Local name of organisation responsible for the Register"]
    gleif_authority_local_name= gleif_authority_temp.iloc[0] if not gleif_authority_temp.empty else None
    gleif_variables["authority_local_name"] = gleif_authority_local_name

    # GLEIF Registration ID (RA Entity ID)
    gleif_reg_ID = json_data["data"]["attributes"]["entity"]["registeredAs"]
    gleif_variables["reg_ID"] = gleif_reg_ID


    gleif_authority_pairs = []
    gleif_authority_pairs.append({
        "authority_ID": gleif_authority_ID,
        "reg_ID": gleif_reg_ID
    })

    # to keep the formatting standardized, try to do it without these getters in the future.
    other_validation_authorities = json_data.get("data", {}).get("attributes", {}).get("registration", {}).get("otherValidationAuthorities", [])
    if other_validation_authorities:
        for other_auth in other_validation_authorities:
            other_authority_ID = other_auth.get("validatedAt", {}).get("id")
            other_reg_ID = other_auth.get("validatedAs")
            if other_authority_ID and other_reg_ID:
                gleif_authority_pairs.append({
                    "authority_ID": other_authority_ID,
                    "reg_ID": other_reg_ID
                })

    gleif_variables["authority_pairs"] = gleif_authority_pairs

    

        

    # GLEIF Legal Name
    gleif_legal_name = json_data["data"]["attributes"]["entity"]["legalName"]["name"]
    gleif_variables["legal_name"] = gleif_legal_name

    # GLEIF Address
    gleif_address_dict = json_data["data"]["attributes"]["entity"]["legalAddress"]
    gleif_address = concat_address_fields(gleif_address_dict)
    gleif_variables["address"] = gleif_address

    # GLEIF Zipcode (Postal Code)
    gleif_zipcode = json_data["data"]["attributes"]["entity"]["legalAddress"]["postalCode"]
    gleif_variables["zipcode"] = gleif_zipcode

    # GLEIF Jurisdiction (Country)
    gleif_jurisdiction = json_data["data"]["attributes"]["entity"]["jurisdiction"]
    gleif_variables["jurisdiction"] = gleif_jurisdiction

    # GLEIF Legal Form
    gleif_legal_form_ID = json_data["data"]["attributes"]["entity"]["legalForm"]["id"]
    gleif_legal_form_temp = df_legal_form.loc[df_legal_form["ELF Code"] == gleif_legal_form_ID, "Entity Legal Form name Local name"]
    gleif_legal_form = gleif_legal_form_temp.iloc[0] if not gleif_legal_form_temp.empty else None
    legal_form_short_series = df_legal_form.loc[df_legal_form["ELF Code"] == gleif_legal_form_ID, "Abbreviations Local language"]
    gleif_legal_form_short = legal_form_short_series.iloc[0] if not legal_form_short_series.empty else None
    gleif_legal_form_other = json_data["data"]["attributes"]["entity"]["legalForm"]["other"]
    
    gleif_variables["legal_form"] = gleif_legal_form
    gleif_variables["legal_form_short"] = gleif_legal_form_short
    gleif_variables["legal_form_other"] = gleif_legal_form_other

    return gleif_variables


def extract_zipcode(address: str, jurisdiction_iso: str) -> str:
    '''
    Extracts the zipcode from an address string using a regex pattern
    specific to the jurisdiction (country ISO code).
    
    :param address: Address string to search for zipcode
    :param jurisdiction_iso: Country ISO code (e.g., 'US', 'DE', 'GB')
    :return: Extracted zipcode or None if not found
    '''
    if not address or not jurisdiction_iso:
        return None
    
    # Look up the regex pattern for this jurisdiction
    regex_row = df_zipcode[df_zipcode["Country ISO code"] == jurisdiction_iso]
    
    if regex_row.empty:
        return None
    
    regex_pattern = regex_row.iloc[0]["RegEx"]
    
    if not regex_pattern or pd.isna(regex_pattern):
        return None
    
    # If the pattern is .{1,255}, it's too generic and will match anything - return None
    if regex_pattern.strip() == ".{1,255}":
        return None
    
    # Apply the regex to extract the zipcode
    match = re.search(regex_pattern, address)
    
    if match:
        return match.group(0)
    
    return None


def concat_address_fields(address: dict) -> str:
    '''
    Concatenates the relevant fields of the address dictionary into a single string, 
    while ignoring certain keys and handling None values and lists appropriately.
    
    :param address: Address dictionary containing various address fields
    :type address: dict
    :return: Description
    :rtype: str
    '''
    ignore_keys = {"language", "region", "country"}
    parts = []

    for key, value in address.items():
        if key in ignore_keys:
            continue

        if value is None:
            continue

        if isinstance(value, list):
            if not value:  # lista vazia
                continue
            parts.extend(str(v) for v in value if v)

        else:
            parts.append(str(value))

    return ", ".join(parts)

def fetch_all_gleif_vars():
    """
    Runs duplicate checks for all LEIs found in the duplicates message, 
    and stores the results in session state.

    Important: the fetch_gleif_vars function doens't really perform a duplicate check!!
    This needs to be addressed in the future. 
    """
    st.session_state.all_gleif_duplicates = []
    st.session_state.skipped_leis = []
    st.session_state.was_a_lei_skipped = False
    duplicate_leis = st.session_state.duplicate_leis
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, lei in enumerate(duplicate_leis):
        # Update progress bar and status
        progress = (i + 1) / len(duplicate_leis)
        progress_bar.progress(progress)
        status_text.text(f"Fetching GLEIF data: {i + 1} of {len(duplicate_leis)} LEIs...")
        
        result = fetch_gleif_vars(lei)
        if result is not None:
            st.session_state.all_gleif_duplicates.append(result)
    
    # Clear the progress bar and status when done
    progress_bar.empty()
    status_text.empty()
    

def extract_lei_manager_vars(text_lei_manager, debug=False):

    """
    Extracts manager_vars from the full text of the LEI Manager.
    These are the variables of the company we want to check for duplicates.

    Parameters:
    - text_lei_manager (str): full text of the LEI Manager
    - debug (bool): if True, prints the extracted values

    Returns:
    - manager_vars (dict): dictionary containing all extracted variables
    """
    manager_vars = {}

    # Legal Name
    legal_name_match = re.search(
        r"Legal Name:\s*\n\([^)]*\)\s*(.*?)\s*\(\s*GLEIF Search\s*\)",
        text_lei_manager,
        re.DOTALL
    )
    manager_legal_name = legal_name_match.group(1).strip() if legal_name_match else None
    manager_vars["legal_name"] = manager_legal_name

    # Entity Category
    entity_category_match = re.search(r"Entity Category:(.+)", text_lei_manager)
    manager_entity_category = entity_category_match.group(1).strip() if entity_category_match else None
    manager_vars["entity_category"] = manager_entity_category

    # Registration Authority Entity ID
    ra_entity_id_match = re.search(r"Validation Authority Entity ID:(.+)", text_lei_manager)
    manager_ra_entity_id = ra_entity_id_match.group(1).strip() if ra_entity_id_match else None
    manager_vars["reg_ID"] = manager_ra_entity_id

    # Authority ID (The authority itself)
    authority_ID_match = re.search(r"Validation Authority ID:.*?\(\s*([A-Z0-9]+)\s*\)", text_lei_manager)
    manager_authority_ID = authority_ID_match.group(1).strip() if authority_ID_match else None
    manager_vars["authority_ID"] = manager_authority_ID

    manager_authority_pairs = []

    # Find ALL Validation Authority Entity IDs
    entity_id_pattern = r"Validation Authority Entity ID:(.+)"
    entity_ids = re.findall(entity_id_pattern, text_lei_manager)

    # Find ALL Validation Authority IDs
    authority_id_pattern = r"Validation Authority ID:.*?\(\s*([A-Z0-9]+)\s*\)"
    authority_ids = re.findall(authority_id_pattern, text_lei_manager)

    # Pair them together
    for auth_id, entity_id in zip(authority_ids, entity_ids):
        manager_authority_pairs.append({
            "authority_ID": auth_id.strip(),
            "reg_ID": entity_id.strip()
        })
    
    manager_vars["authority_pairs"] = manager_authority_pairs

    # Legal Form
    legal_form_match = re.search(r"Legal Form:(.+?)\s*\(", text_lei_manager)
    manager_legal_form = legal_form_match.group(1).strip() if legal_form_match else None
    manager_vars["legal_form"] = manager_legal_form

    # Entity Creation Date
    creation_date_match = re.search(r"Entity Creation Date:(.+)", text_lei_manager)
    manager_creation_date = None
    if creation_date_match:
        try:
            dt = datetime.strptime(creation_date_match.group(1).strip(), "%Y-%m-%d %H:%M %z")
            manager_creation_date = dt.date()
        except Exception:
            manager_creation_date = creation_date_match.group(1).strip()  # fallback string
    manager_vars["date"] = manager_creation_date

    # Legal Address
    address_match = re.search(
        r"Legal Address:\s*.*?\nLegal Address:\s*\([^\)]*\)\s*(.+?)(?=Headquarters Address:)",
        text_lei_manager,
        re.DOTALL | re.IGNORECASE
    )
    manager_address = address_match.group(1).strip() if address_match else None
    manager_vars["address"] = manager_address

    #Legal Jurisdiction (Country)
    jurisdiction_match = re.search(r"Legal Jurisdiction:.*\(([^)]+)\)", text_lei_manager)
    manager_jurisdiction = jurisdiction_match.group(1).strip() if jurisdiction_match else None
    manager_vars["jurisdiction"] = manager_jurisdiction

    # Extract Zipcode using jurisdiction ISO code and address
    manager_zipcode = extract_zipcode(manager_address, manager_jurisdiction) if manager_address and manager_jurisdiction else None
    manager_vars["zipcode"] = manager_zipcode

    # Contact Partner
    contact_partner_match = re.search(
        r"Contact partner\s*\n\s*(.+)\s*\n\s*(.+)",
        text_lei_manager,
        re.IGNORECASE
    )
    if contact_partner_match:
        contact_company = contact_partner_match.group(1).strip()
        contact_person = contact_partner_match.group(2).strip()
    else:
        contact_company = None
        contact_person = None
    manager_vars["contact_company"] = contact_company
    manager_vars["contact_person"] = contact_person

    # Debug prints
    if debug:
        print("Company's Legal Name:", manager_legal_name)
        print("Entity Category:", manager_entity_category)
        print("Registration ID:", manager_ra_entity_id)
        print("Legal Form:", manager_legal_form)
        print("Creation Date:", manager_creation_date)
        print("Legal Address:", manager_address)
        print("Contact company:", contact_company)
        print("Contact person:", contact_person)
        pprint(manager_vars)

    st.session_state.manager_vars = manager_vars

    return manager_vars

def authority_ID_check(gleif_authority_ID, manager_authority_ID):

    if gleif_authority_ID in {"RA777777", "RA888888", "RA999999"} or manager_authority_ID in {"RA777777", "RA888888", "RA999999"}:
        return 50  # N/A, não é possível comparar
    authority_ID_score = fuzz.ratio(gleif_authority_ID, manager_authority_ID)
    if authority_ID_score == 100:
        return authority_ID_score # returns 100 if they are the same
    elif authority_ID_score is not None and authority_ID_score < 100:
        return 0
    return 0  # Fallback: return 0 if score is None or any other case
    
def find_best_authority_match(gleif_authority_pairs, manager_authority_pairs, manager_jurisdiction):
   
    if not gleif_authority_pairs or not manager_authority_pairs:
        return None, None, None, None

    # Start with first result from each list as baseline
    best_gleif_pair = gleif_authority_pairs[0]
    best_manager_pair = manager_authority_pairs[0]

    best_authority_score = authority_ID_check(best_gleif_pair["authority_ID"], best_manager_pair["authority_ID"])
    best_reg_ID_score = fuzz.ratio(str(best_gleif_pair["reg_ID"]), str(best_manager_pair["reg_ID"])) if best_gleif_pair.get("reg_ID") and best_manager_pair.get("reg_ID") else None

    if best_authority_score != 100:
        for gleif_pair in gleif_authority_pairs:
            for manager_pair in manager_authority_pairs:
                current_authority_score = authority_ID_check(gleif_pair["authority_ID"], manager_pair["authority_ID"])
                if current_authority_score == 100:
                    current_reg_ID_score = fuzz.ratio(str(gleif_pair["reg_ID"]), str(manager_pair["reg_ID"])) if gleif_pair.get("reg_ID") and manager_pair.get("reg_ID") else None
                    best_reg_ID_score = current_reg_ID_score
                    best_authority_score = current_authority_score
                    best_gleif_pair = gleif_pair
                    best_manager_pair = manager_pair

    if manager_jurisdiction in JURISDICTION_HANDLERS:
        config = JURISDICTION_HANDLERS[manager_jurisdiction]
        best_authority_score = config["function"]()
    
    return best_gleif_pair, best_manager_pair, best_authority_score, best_reg_ID_score




def generate_results():

    st.session_state.all_results = []
    
    all_results = []
    manager_vars = st.session_state.manager_vars
    all_gleif_duplicates = st.session_state.all_gleif_duplicates

    for duplicate in all_gleif_duplicates:

        gleif_variables = duplicate
        
        # Beginning of Authority and Registration ID
        gleif_authority_pairs = gleif_variables.get("authority_pairs", [])
        manager_authority_pairs = manager_vars.get("authority_pairs", [])

        best_gleif_pair, best_manager_pair, authority_ID_score, reg_ID_score = find_best_authority_match(
            gleif_authority_pairs, 
            manager_authority_pairs, 
            manager_vars.get("jurisdiction")
        )

        manager_vars["authority_ID"] = best_manager_pair["authority_ID"] if best_manager_pair else manager_vars["authority_ID"]
        manager_vars["reg_ID"] = best_manager_pair["reg_ID"] if best_manager_pair else manager_vars["reg_ID"]
        gleif_variables["authority_ID"] = best_gleif_pair["authority_ID"] if best_gleif_pair else gleif_variables["authority_ID"]
        gleif_variables["reg_ID"] = best_gleif_pair["reg_ID"] if best_gleif_pair else gleif_variables["reg_ID"]     

        # Im not sure this makes sense here. Maybe this check should be done before, like inside find_best_authority_match.
        if manager_vars["authority_ID"] in AUTHORITY_HANDLERS:
            function = AUTHORITY_HANDLERS[manager_vars["authority_ID"]]
            reg_ID_score = function(gleif_variables["reg_ID"], manager_vars["reg_ID"], reg_ID_score)

        # End of Authority and Registration ID

        legal_name_score = fuzz.ratio(str(gleif_variables["legal_name"]).lower(), str(manager_vars["legal_name"]).lower()) if gleif_variables.get("legal_name") and manager_vars.get("legal_name") else None
        
        address_score_partial = fuzz.partial_ratio(str(gleif_variables["address"]).lower(), str(manager_vars["address"]).lower()) if gleif_variables.get("address") and manager_vars.get("address") else None
        address_score_token_set = fuzz.token_set_ratio(str(gleif_variables["address"]).lower(), str(manager_vars["address"]).lower()) if gleif_variables.get("address") and manager_vars.get("address") else None
        address_score = max(address_score_partial, address_score_token_set) if address_score_partial is not None and address_score_token_set is not None else address_score_partial or address_score_token_set
        
        date_score = abs((gleif_variables["date"].date() - manager_vars["date"]).days) if gleif_variables.get("date") and manager_vars.get("date") else None

        legal_form_score_main = fuzz.partial_ratio(str(gleif_variables["legal_form"]).lower(), str(manager_vars["legal_form"]).lower().strip())
        legal_form_short_score = fuzz.partial_ratio(str(gleif_variables["legal_form_short"]).lower(), str(manager_vars["legal_form"]).lower().strip())
        legal_form_other_score = fuzz.partial_ratio(str(gleif_variables["legal_form_other"]).lower(), str(manager_vars["legal_form"]).lower().strip())
        legal_form_score = max(legal_form_score_main, legal_form_short_score, legal_form_other_score) if legal_form_score_main is not None and legal_form_short_score is not None and legal_form_other_score is not None else legal_form_score_main or legal_form_short_score or legal_form_other_score

        zipcode_score = fuzz.ratio(str(gleif_variables["zipcode"]), str(manager_vars["zipcode"])) if gleif_variables.get("zipcode") and manager_vars.get("zipcode") else None


        results = {
            "Legal Name": legal_name_score,
            "Authority ID": authority_ID_score,
            "Registration ID": reg_ID_score, 
            "Address": address_score, 
            "ZIP Code": zipcode_score,
            "Creation Date": date_score,
            "Legal Form": legal_form_score,
        }

        all_results.append(results)
        st.session_state.all_results = all_results
        st.session_state.gleif_variables = gleif_variables

    return all_results


def is_streamlit_running():
    try:
        return get_script_run_ctx() is not None
    except:
        return False


def get_feature_row_color(feature, value):
    if value is None:
        return ""
    
    # Authority ID gets a special treatment. Only yellow (if different) or no-color otherwise.
    if "Authority ID" in feature: # Substring check. Also works for cases like "Authority ID ⚠️ Different".
        if value == 0:
            return "background-color: #ffeb9c"   # amarelo se não for identico
        else:
            return ""# sem cor para casos como RA777777, RA888888 ou RA999999, ou quando são identicos.
        
    # Legal Name e Legal Form não precisão de cor
    if feature == "Legal Name" or feature == "Legal Form":
        return ""
    
    #Creation Date tem uma lógica invertida, quanto menor a diferença de dias, mais parecido é.
    if feature == "Creation Date":
        if value <= SCORE_THRESHOLDS["Creation Date"]["RED"]:
            return "background-color: #ffc7ce"   # vermelho
        elif value <= SCORE_THRESHOLDS["Creation Date"]["YELLOW"]:
            return "background-color: #ffeb9c"   # amarelo
        else:
            return "background-color: #c6efce"   # verde
        
    # ZIP Code tem threshold mais rígido, já que é um string tão pequeno    
    if feature == "ZIP Code":
        if value >= SCORE_THRESHOLDS["ZIP Code"]["RED"]:
            return "background-color: #ffc7ce" # vermelho
        elif value >= SCORE_THRESHOLDS["ZIP Code"]["YELLOW"]:
            return "background-color: #ffeb9c" # amarelo
        else:
            return "background-color: #c6efce" # verde
        
    if feature == "Registration ID":
        if value >= SCORE_THRESHOLDS["Registration ID"]["RED"]:
            return "background-color: #ffc7ce" # vermelho
        elif value >= SCORE_THRESHOLDS["Registration ID"]["YELLOW"]:
            return "background-color: #ffeb9c" # amarelo
        else:
            return "background-color: #c6efce" # verde
        
        
    # Demais casos (atualmente só Address):
    else:
        if value >= SCORE_THRESHOLDS["Address"]["RED"]:
            return "background-color: #ffc7ce" #RED
        elif value >= SCORE_THRESHOLDS["Address"]["YELLOW"]:
            return "background-color: #ffeb9c" #YELLOW
        else:
            return "background-color: #c6efce"


def build_comparison_table(results, gleif_vars, manager_vars):

    rows = []

    for feature, score in results.items():

        key = FEATURE_KEY_MAP.get(feature)

        manager_value = manager_vars.get(key) if key else None
        gleif_value = gleif_vars.get(key) if key else None

        # fallback inteligente para Legal Form
        if feature == "Legal Form" and not gleif_value:
            gleif_value = gleif_vars.get("legal_form_other")

        # Convert date objects to strings for Arrow serialization
        if hasattr(manager_value, 'isoformat'):
            iso_str = manager_value.isoformat()
            manager_value = iso_str[:10]  # Truncate to YYYY-MM-DD
        if hasattr(gleif_value, 'isoformat'):
            iso_str = gleif_value.isoformat()
            gleif_value = iso_str[:10]  # Truncate to YYYY-MM-DD

        # Add warning indicator for mismatched Authority ID
        feature_display = feature
        if feature == "Authority ID" and score == 0:
            feature_display = feature + " ⚠️ Different"

        rows.append({
            "Feature": feature_display,
            "LEI Manager": manager_value,
            "GLEIF Candidate": gleif_value,
            "Score": score
        })

    df = pd.DataFrame(rows)


    styled_df = df.style.apply(
        # Applies the get_feature_row_color function to each row, passing the feature name and score to determine the background color for the entire row.
        lambda row: [get_feature_row_color(row["Feature"], float(row["Score"]))] * 4, # Multiplied by 4 to apply the same color to all columns in the row. (Which I am still skeptical about, but ok).
        axis=1 # Axis 1 means we apply the function to each row. 
    ).format({"Score": "{:.0f}"}) # Removes decimal points for the score

    return styled_df

def plot_scores(scores_list, title="Feature Similarity Scores"):

    if isinstance(scores_list, dict):
        scores_list = list(scores_list.items())

    # Ordena decrescente
    scores_list_sorted = sorted(scores_list, key=lambda x: x[1], reverse=True)
    features = [item[0] for item in scores_list_sorted]
    values = [item[1] for item in scores_list_sorted]

    # Define cores
    colors = []
    for feature, v in zip(features, values):
        if feature == "Creation Date":
            if v <= 7:
                colors.append("green")
            elif v <= 30:
                colors.append("yellow")
            else:
                colors.append("red")
        else:
            if v >= 90:
                colors.append("green")
            elif v >= 70:
                colors.append("orange")
            else:
                colors.append("red")

    fig = plt.figure(figsize=(10,5))
    bars = plt.bar(features, values, color=colors)

    plt.ylabel("Score / Days")
    plt.title(title)
    plt.ylim(0, 110)

    # Linha horizontal no valor 100
    plt.axhline(y=100, color='blue', linestyle='--', linewidth=1)
    plt.text(0, 102, "100", color='blue', fontsize=10, va='bottom')

    # Valores acima das barras
    for bar, value in zip(bars, values):
        text_y = min(value + 2, 108)
        plt.text(
            bar.get_x() + bar.get_width()/2,
            text_y,
            f"{value:.0f}",
            ha='center',
            va='bottom',
            fontsize=9
        )

    # Nome das colunas colorido igual à barra
    ax = plt.gca()
    for ticklabel, color in zip(ax.get_xticklabels(), colors):
        ticklabel.set_color(color)

    plt.xticks(rotation=0)
    plt.tight_layout()

    # 🔑 STREAMLIT
    if is_streamlit_running():
        st.pyplot(fig, clear_figure=True)
    else:
        plt.show()


def classify_candidate_emoji_color(results):
    """
    Classifies duplicate candidates based on their similarity scores for key features,
    using predefined thresholds to determine if they are 
        -likely duplicates (RED), 
        -possible duplicates (YELLOW), or 
        -unlikely duplicates (GREEN). 
    Retorna: GREEN, YELLOW ou RED
    """

    scores = results

    authority_ID = scores.get("Authority ID")
    reg_ID = scores.get("Registration ID")
    legal_name = scores.get("Legal Name")
    address = scores.get("Address")
    legal_form = scores.get("Legal Form")
    date = scores.get("Creation Date")
    zipcode = scores.get("ZIP Code")

    # Se faltar algo essencial
    if legal_name is None or address is None or date is None:
        return "UNKNOWN"

    # =========================
    # 🔴 PROVÁVEL DUPLICATA
    # =========================
    if (
        (address is not None and address >= SCORE_THRESHOLDS["Address"]["RED"])
        or (reg_ID is not None and reg_ID >= SCORE_THRESHOLDS["Registration ID"]["RED"])
        # Eu removi o check do ZIP_code do vermelho, pq só um cep igual nao é suficiente pra garantir duplicate. Ainda temos o check amarelo do ZIP, ta bom o suficiente.
    ):
        return "RED"

    # =========================
    # 🟡 POSSÍVEL DUPLICATA
    # =========================
    if (
        (address is not None and address >= SCORE_THRESHOLDS["Address"]["YELLOW"])
        or ((reg_ID is None and authority_ID != 50) or (reg_ID is not None and reg_ID >= SCORE_THRESHOLDS["Registration ID"]["YELLOW"])) # Só vai dar amarelo se nao tiver authority_ID E não for um caso de RA777777, RA888888 ou RA999999 (que tem authority_ID score de 50).
        or (zipcode is not None and zipcode >= SCORE_THRESHOLDS["ZIP Code"]["YELLOW"])
    ):
        return "YELLOW"  

    # =========================
    # 🟢 POUCO PROVÁVEL
    # =========================
    return "GREEN"

# Buttons and TextAreas

if st.button("Reset Variables"):
    st.session_state.clear()
    st.success("All variables have been reset")



st.subheader("Duplicates LEIs")

duplicates_text = st.text_area(
    "Paste duplicates message here",
    height=200
)

if st.button("Process duplicates", use_container_width=True):

    # st.session_state.clear() # duvida: isso vai apagar o duplicates_text?

    if duplicates_text.strip():
        st.session_state.duplicate_leis = re.findall(
            pattern,
            duplicates_text,
            flags=re.MULTILINE
        )

        matches = re.findall(pattern_lei_status, duplicates_text, re.DOTALL)
        lei_status_pairs = {lei: status for lei, status in matches}
        st.session_state.lei_status_pairs = lei_status_pairs

        # Extract the total duplicate count from the message and compare
        duplicate_count_match = re.search(pattern_duplicate_count, duplicates_text)
        if duplicate_count_match:
            total_duplicates = int(duplicate_count_match.group(1))
            found_leis_count = len(st.session_state.duplicate_leis)
            if total_duplicates > found_leis_count:
                missing_leis_count = total_duplicates - found_leis_count
                st.session_state.missing_leis_count = missing_leis_count
                st.warning(f"**{missing_leis_count} LEI(s)** mentioned in the duplicate count were not found in the extracted list. This may be due to formatting issues in the message. **Make sure to check the remaining LEI(s) as well.**")
            else:
                st.session_state.missing_leis_count = None

        if st.session_state.duplicate_leis:
            st.success(f"{len(st.session_state.duplicate_leis)} LEI(s) found:")
            for lei in st.session_state.duplicate_leis:
                status = lei_status_pairs.get(lei)
                if status and status != "ISSUED":
                    st.write(f"{lei} - {status}")
                else:
                    st.write(lei)

            # Here we have the spinner, which shows an animated loading circle icon.

            # with st.spinner("Fetching GLEIF data for all LEIs..."):
                # fetch_all_gleif_vars()
            fetch_all_gleif_vars()
        else:
            st.warning("No LEI-Number found (duplicates)")
    else:
        st.warning("Please paste some text first.")


st.subheader("LEI Manager Data")

manager_text = st.text_area(
    "Paste the LEI Manager full text here",
    height=300
)

if st.button("Process LEI Manager", use_container_width=True):
    
    if manager_text.strip():
        manager_vars = extract_lei_manager_vars(manager_text)
        if manager_vars["legal_name"] is not None:
            st.success("LEI Manager information extracted successfully")
            if manager_vars["jurisdiction"] and manager_vars["jurisdiction"] in JURISDICTION_HANDLERS:
                config = JURISDICTION_HANDLERS[manager_vars["jurisdiction"]]
                getattr(st, config["severity"])(config["message"])
        else:
            # Usually the most common reason for this is the 
            # LEI Manager's languagenot being changed to english
            st.warning("Data not found. Check if your lei-manager is in english")

    else:
        st.warning("Please paste the LEI Manager text first.")


if st.button("Check Duplicates", use_container_width=True):

    st.write("Initializing duplicate check...")
    all_results = generate_results()
    status_log = []
    findings = "No duplicates found! You may aprove the order. See below for more details."
    is_there_a_duplicate = False
    there_is_at_least_one_authority_mismatch = False
    has_yellow = False
    duplicate_leis = st.session_state.duplicate_leis
    all_gleif_duplicates = st.session_state.all_gleif_duplicates
    was_a_lei_skipped = st.session_state.was_a_lei_skipped

    # Check duplicates and authority mismatches in a single pass
    for i, results in enumerate(all_results):
        # Check authority ID
        authority_id_score = results.get("Authority ID")
        
        if authority_id_score == 0:
            there_is_at_least_one_authority_mismatch = True
        
        # Classify duplicate
        status = classify_candidate_emoji_color(results)
        status_log.append(status)
        
        if status == "RED":
            findings = f"DUPLICATE ALERT: {duplicate_leis[i]}\n"
            is_there_a_duplicate = True
            st.error(findings)
        elif status == "YELLOW":
            has_yellow = True

    # Show single warning if any authority mismatches exist
    if there_is_at_least_one_authority_mismatch:
        st.warning("⚠️ One or more candidates have a **different Registration Authority ID.**  These should be checked individually.")    
    if was_a_lei_skipped:
        warning_msg = "⚠️ The following LEIs could not be fetched and **must be reviewed manually:** \n\n"
        
        for skipped_lei_info in st.session_state.skipped_leis:
            lei = skipped_lei_info["lei"]
            status = skipped_lei_info["status"]
            error_code = skipped_lei_info["error_code"]
            
            if status == "PENDING_VALIDATION":
                warning_msg += f"- {lei} — {status}\n"
            else:
                warning_msg += f"- {lei} ({error_code})\n"
        
        st.warning(warning_msg)
    # Show appropriate final status
    if is_there_a_duplicate:
        pass # (RED ERROr message was already shown.)
    elif has_yellow:
        st.warning("Possible duplicates found. Please review the details below before approving the order.")
    elif not (there_is_at_least_one_authority_mismatch or was_a_lei_skipped):
        st.success(findings)





    # Display results for each candidate with appropriate emojis and warnings
    for i, results in enumerate(all_results):
        
        status = status_log[i]
        
        emoji = {
            "GREEN": "🟢",
            "YELLOW": "🟡",
            "RED": "🔴"
        }[status]

        
        gleif_vars = all_gleif_duplicates[i]
        lei_code = duplicate_leis[i]
        
        # Check if Authority ID is 0 (different)
        authority_warning = " ⚠️ DIFFERENT AUTHORITY" if results.get("Authority ID") == 0 else ""

        with st.expander(f"{emoji} Duplicate candidate: {lei_code}{authority_warning}"):

            styled_table = build_comparison_table(
                results,
                gleif_vars,
                st.session_state.manager_vars
            )

            st.dataframe(styled_table)