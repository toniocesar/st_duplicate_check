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
from st_copy import copy_button


### Variable Declarations

if "duplicate_leis" not in st.session_state: # stores all leis found in the duplicates_text. LEIs are stored in order of apperance. Each LEI will only appear once (if it is mentioned more than once in the duplicates message, it will still only be stored once in this list)
    st.session_state.duplicate_leis = []
    duplicate_leis = st.session_state.duplicate_leis
    
if "processed_leis" not in st.session_state: # all duplicate_leis that are not skipped. This is what we mostly use because we dont need the skipped leis anymore.
    st.session_state.processed_leis = []
    processed_leis = st.session_state.processed_leis

if "all_gleif_duplicates" not in st.session_state: # list with all processed LEIs. Each entry contains all gleif features for this LEI. This is done by appending the return of the fetch_gleif_vars function. They are retreived via API, or through the advanced regex function if the API call returns an error.
    st.session_state.all_gleif_duplicates = [] # Created by: appending all non-None results from fetch_gleif_vars. Reset in fetch_all_gleif_vars (right after clicking Process Duplicates)
    all_gleif_duplicates = st.session_state.all_gleif_duplicates # Used for: generate_results and build_comparison_table

if "all_results" not in st.session_state: # list with all results of the comparison between GLEIF and Manager data. Each item in the list is a dictionary with all features and scores for a given LEI.
    st.session_state.all_results = []
    all_results = st.session_state.all_results

if "manager_vars" not in st.session_state: # Contains all features extracted from the current company inn LEI-Manager
    st.session_state.manager_vars = {}
    manager_vars = st.session_state.manager_vars

if "lei_status_pairs" not in st.session_state: # Uses a unique regex to grab a lei and its status (ISSUED, LAPSED etc.) from the duplicates message. This needs a rework, since I believe its only grabbing the status if it appears a certain fixed number of lines down.
    st.session_state.lei_status_pairs = {}
    lei_status_pairs = st.session_state.lei_status_pairs

if "missing_leis_count" not in st.session_state: # Currently, this is only used inside the "Process Duplicates" button to issue a warning if not all leis are present in the duplicates message (likely because of the max character limit of 10000 characters). This means we dont even need this as a session state right now. However, we should use this session state to issue a warning in the end (when pressing the "Check Duplicates" button) to remind operators that not all leis may have been processed.
    st.session_state.missing_leis_count = None
    missing_leis_count = st.session_state.missing_leis_count

if "was_a_lei_skipped" not in st.session_state: # Indicates if any LEI was skipped during processing
    st.session_state.was_a_lei_skipped = False
    was_a_lei_skipped = st.session_state.was_a_lei_skipped

if "skipped_leis" not in st.session_state: # List of LEIs that were skipped during processing
    st.session_state.skipped_leis = []
    skipped_leis = st.session_state.skipped_leis

if "red_labeled_duplicates" not in st.session_state: # Stores all duplicates that received a RED label, meaning they are likely duplicates. This is used for the final display of results.
    st.session_state.red_labeled_duplicates = []
    red_labeled_duplicates = st.session_state.red_labeled_duplicates

if "yellow_labeled_duplicates" not in st.session_state: # Stores all duplicates that received a YELLOW label, meaning they are possible duplicates. This is used for the final display of results.
    st.session_state.yellow_labeled_duplicates = []
    yellow_labeled_duplicates = st.session_state.yellow_labeled_duplicates

if "different_authority_candidates" not in st.session_state: # Stores all duplicates that have different authorities. This is used for the final display of results.
    st.session_state.different_authority_candidates = []
    different_authority_candidates = st.session_state.different_authority_candidates

if "results_duplicates_regex" not in st.session_state: # Stores the results of the advanced regex function that extracts data from the duplicates message. This is used to complement the data retrieved from the API, in cases where the API returns an error (eg because the LEI is in PENDING_VALIDATION status, and therefore not yet searchable in the GLEIF database).
    st.session_state.results_duplicates_regex = []
    results_duplicates_regex = st.session_state.results_duplicates_regex


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
pattern_duplicate_count = r'(\d+)\s+duplicate\(s\)\s+found'
url_stem = "https://api.gleif.org/api/v1/lei-records/"

def handle_GST_PAN_reg_ID(gleif_reg_ID: str, manager_reg_ID: str, current_score: float) -> float   :
    """
    Called by the "Check Duplicates" button (through the generate_results function).
    
    Custom handling for GST/PAN Registration IDs (specific to RA000754 - India).
    Since the PAN number is embedded within the GSTRegistration ID and is a critical identifier,
    we must consider this test
    """
    pan_score = fuzz.ratio(gleif_reg_ID[2:-3], manager_reg_ID[2:-3]) if gleif_reg_ID and manager_reg_ID else None
    return max(current_score, pan_score) if pan_score is not None else current_score

def handle_no_authority_check() -> float:
    """
    Called by the "Check Duplicates" button (through the find_best_authority_match function).
    
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

# Note: currently, authority handlers are called AFTER the "best authority" has been selected
AUTHORITY_HANDLERS = {
    "RA000754": handle_GST_PAN_reg_ID,
}

# Note: currently, jurisdiction handlers are called AFTER the "best authority" has been selected
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

# Maximum numeric difference between trailing numeric suffixes of two reg_IDs
# for them to be considered "incremental" (batch-registered companies).
INCREMENTAL_REG_ID_DIFF = 1

def rule_incremental_reg_id(base_color: str, scores: dict, gleif_vars: dict, manager_vars: dict) -> str | None:
    """
    Override rule: downgrades RED → YELLOW for batch-registered companies
    (e.g. India), where multiple similar companies share the same address and
    creation date but have incrementally different reg_IDs and similar-but-not-identical names.

    Fires when ALL of the following are true:
    - base classification is RED
    - legal name score is high but not identical
      (>= Address RED threshold as a proxy, and < 100)
    - address score is >= Address RED threshold
    - creation date difference is <= Creation Date YELLOW threshold
    - the trailing numeric suffixes of both reg_IDs differ by <= INCREMENTAL_REG_ID_DIFF
    """
    if base_color != "RED":
        return None

    legal_name = scores.get("Legal Name")
    address    = scores.get("Address")
    date       = scores.get("Creation Date")

    name_threshold = SCORE_THRESHOLDS["Registration ID"]["RED"]

    # Name must be similar but not identical
    if legal_name is None or not (legal_name >= name_threshold and legal_name < 100):
        return None

    # Address must be highly similar
    if address is None or address < SCORE_THRESHOLDS["Address"]["RED"]:
        return None

    # Dates must be close
    if date is None or date > SCORE_THRESHOLDS["Creation Date"]["YELLOW"]:
        return None

    # reg_IDs must differ by at most INCREMENTAL_REG_ID_DIFF in their trailing numeric suffix
    gleif_reg_id   = gleif_vars.get("reg_ID")   if gleif_vars   else None
    manager_reg_id = manager_vars.get("reg_ID") if manager_vars else None

    if not gleif_reg_id or not manager_reg_id:
        return None

    gleif_suffix   = re.search(r'\d+$', str(gleif_reg_id))
    manager_suffix = re.search(r'\d+$', str(manager_reg_id))

    if not gleif_suffix or not manager_suffix:
        return None

    if abs(int(gleif_suffix.group()) - int(manager_suffix.group())) <= INCREMENTAL_REG_ID_DIFF:
        return "YELLOW"

    return None


# List of classification override rule functions.
# Each callable has signature:
#   (base_color: str, scores: dict, gleif_vars: dict, manager_vars: dict) -> str | None
# Return a new color string to override, or None to leave the color unchanged.
# Rules are applied in order; each rule receives the output of the previous one.
CLASSIFICATION_OVERRIDE_RULES = [rule_incremental_reg_id]


# Reading of dictionaries

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# === DATA LOADING ===

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

# === DATA FETCHING ===

def _build_authority_pairs_from_json(json_data: dict) -> list:
    """
    Extracts authority pairs from GLEIF API JSON response.
    Includes both primary registration authority and other validation authorities.
    """
    authority_pairs = []
    
    # Primary registration authority
    primary_authority_ID = json_data["data"]["attributes"]["entity"]["registeredAt"]["id"]
    primary_reg_ID = json_data["data"]["attributes"]["entity"]["registeredAs"]
    authority_pairs.append({
        "authority_ID": primary_authority_ID,
        "reg_ID": primary_reg_ID
    })
    
    # Other validation authorities
    other_validation_authorities = json_data.get("data", {}).get("attributes", {}).get("registration", {}).get("otherValidationAuthorities", [])
    if other_validation_authorities:
        for other_auth in other_validation_authorities:
            other_authority_ID = other_auth.get("validatedAt", {}).get("id")
            other_reg_ID = other_auth.get("validatedAs")
            if other_authority_ID and other_reg_ID:
                authority_pairs.append({
                    "authority_ID": other_authority_ID,
                    "reg_ID": other_reg_ID
                })
    
    return authority_pairs


def _fetch_gleif_via_api(lei: str) -> dict | None:
    """
    Fetches GLEIF data via API call and extracts all fields from JSON response.
    Returns complete gleif_variables dict if successful, None if API call fails.
    """
    url = f"{url_stem}{lei}"
    page = requests.get(url)
    
    if page.status_code != 200:
        return None
    
    json_data = page.json()
    gleif_variables = {}
    
    # Extract date
    DEFAULT_DATE = datetime(1, 1, 1)
    gleif_date = json_data["data"]["attributes"]["entity"]["creationDate"]
    gleif_variables["date"] = (
        DEFAULT_DATE if gleif_date is None 
        else datetime.fromisoformat(gleif_date).replace(tzinfo=None)
    )
    
    # Extract authority ID and local name
    gleif_authority_ID = json_data["data"]["attributes"]["entity"]["registeredAt"]["id"]
    gleif_variables["authority_ID"] = gleif_authority_ID
    
    gleif_authority_temp = df_gleif_authority.loc[
        df_gleif_authority["Registration Authority Code"] == gleif_authority_ID, 
        "Local name of organisation responsible for the Register"
    ]
    gleif_authority_local_name = gleif_authority_temp.iloc[0] if not gleif_authority_temp.empty else None
    gleif_variables["authority_local_name"] = gleif_authority_local_name
    
    # Extract registration ID and build authority pairs
    gleif_reg_ID = json_data["data"]["attributes"]["entity"]["registeredAs"]
    gleif_variables["reg_ID"] = gleif_reg_ID
    gleif_variables["authority_pairs"] = _build_authority_pairs_from_json(json_data)
    
    # Extract legal name
    gleif_variables["legal_name"] = json_data["data"]["attributes"]["entity"]["legalName"]["name"]
    
    # Extract address and zipcode
    gleif_address_dict = json_data["data"]["attributes"]["entity"]["legalAddress"]
    gleif_variables["address"] = concat_address_fields(gleif_address_dict)
    gleif_variables["zipcode"] = json_data["data"]["attributes"]["entity"]["legalAddress"]["postalCode"]
    
    # Extract jurisdiction
    gleif_variables["jurisdiction"] = json_data["data"]["attributes"]["entity"]["jurisdiction"]
    
    # Extract legal form (main, short, and other)
    gleif_legal_form_ID = json_data["data"]["attributes"]["entity"]["legalForm"]["id"]
    
    gleif_legal_form_temp = df_legal_form.loc[
        df_legal_form["ELF Code"] == gleif_legal_form_ID, 
        "Entity Legal Form name Local name"
    ]
    gleif_variables["legal_form"] = gleif_legal_form_temp.iloc[0] if not gleif_legal_form_temp.empty else None
    
    legal_form_short_series = df_legal_form.loc[
        df_legal_form["ELF Code"] == gleif_legal_form_ID, 
        "Abbreviations Local language"
    ]
    gleif_variables["legal_form_short"] = legal_form_short_series.iloc[0] if not legal_form_short_series.empty else None
    gleif_variables["legal_form_other"] = json_data["data"]["attributes"]["entity"]["legalForm"]["other"]
    
    return gleif_variables


def _fetch_gleif_via_regex(lei: str) -> dict | None:
    """
    Attempts to extract GLEIF data from regex results when API call fails.
    Returns partial gleif_variables dict with available fields, or None if no sufficient data found.
    """
    results_duplicates_regex = st.session_state.results_duplicates_regex
    
    # Find matching LEI in regex results
    extracted_data = None
    for result in results_duplicates_regex:
        if result.get("lei") == lei:
            extracted_data = result
            break
    
    # No data found in regex results, or insufficient information
    if extracted_data is None or extracted_data.get("insufficient_regex_info"):
        return None
    
    # Populate gleif_variables with regex-extracted data
    gleif_variables = {}
    gleif_variables["legal_name"] = extracted_data.get("company_name")
    gleif_variables["zipcode"] = extracted_data.get("zip_code")
    gleif_variables["reg_ID"] = extracted_data.get("registration_id")
    gleif_variables["authority_ID"] = extracted_data.get("authority_id")
    
    # Build authority_pairs from registration data
    authority_pairs = []
    if extracted_data.get("registration_id") and extracted_data.get("authority_id"):
        authority_pairs.append({
            "authority_ID": extracted_data.get("authority_id"),
            "reg_ID": extracted_data.get("registration_id")
        })
    if extracted_data.get("other_registration_pairs"):
        for pair in extracted_data.get("other_registration_pairs"):
            authority_pairs.append({
                "authority_ID": pair.get("authority_id"),
                "reg_ID": pair.get("registration_id")
            })
    gleif_variables["authority_pairs"] = authority_pairs if authority_pairs else []
    
    # Set remaining fields to None (not available from regex)
    gleif_variables["date"] = None
    gleif_variables["authority_local_name"] = None
    gleif_variables["address"] = None
    gleif_variables["jurisdiction"] = None
    gleif_variables["legal_form"] = None
    gleif_variables["legal_form_short"] = None
    gleif_variables["legal_form_other"] = None
    
    return gleif_variables


def _handle_lei_skip(lei: str, status: str, error_code: int) -> None:
    """
    Logs a skipped LEI to session state and displays appropriate warning message.
    """
    st.session_state.was_a_lei_skipped = True
    st.session_state.skipped_leis.append({
        "lei": lei,
        "status": status,
        "error_code": error_code
    })
    
    if error_code == 404:
        st.warning(f"Skipping {lei} — {status}")
    else:
        print(f"\n\n ********** Error searching for LEI {lei} — status {error_code} ********** \n\n")
        st.warning(f"Skipping LEI {lei} — LEI not found ({error_code}) \n\n")


def fetch_gleif_vars(lei: str) -> dict | None:
    """
    Called by the "Process Duplicates" button (through the fetch_all_gleif_vars function).
    
    Retrieves all relevant information from GLEIF API for a given LEI.
    Falls back to regex extraction if API call fails.
    
    :param lei: LEI code to be checked (20-character alphanumeric string)
    :return: gleif_variables dict with extracted fields, or None if LEI is skipped
    """
    lei_status_pairs = st.session_state.lei_status_pairs
    status = lei_status_pairs.get(lei)
    
    #print(f"LEI: {status}")  # Debug print for LEI status
    
    # Try API first
    gleif_variables = _fetch_gleif_via_api(lei)
    if gleif_variables is not None:
        return gleif_variables
    
    # API failed, try regex fallback
    gleif_variables = _fetch_gleif_via_regex(lei)
    if gleif_variables is not None:
        return gleif_variables
    
    # Both API and regex failed
    page = requests.get(f"{url_stem}{lei}")
    _handle_lei_skip(lei, status, page.status_code)
    return None


# === UTILITY FUNCTIONS ===

def extract_zipcode(address: str, jurisdiction_iso: str) -> str | None:
    '''
    Called by the "Process LEI Manager" button (through the extract_lei_manager_vars function).
    
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
    """
    Called by the "Process Duplicates" button (through the fetch_gleif_vars function).
    
    Concatenates the relevant fields of the address dictionary into a single string, 
    while ignoring certain keys and handling None values and lists appropriately.
    
    :param address: Address dictionary containing various address fields
    :type address: dict
    :return: Concatenated address string
    :rtype: str
    """
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
    Called by the "Process Duplicates" button.
    Runs duplicate checks for all LEIs found in the duplicates message, 
    and stores the results in session state.

    Important: the fetch_gleif_vars function doens't really perform a duplicate check!!
    This needs to be addressed in the future. 
    """
    st.session_state.all_gleif_duplicates = []
    st.session_state.processed_leis = []
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
            st.session_state.processed_leis.append(lei)
    
    # Clear the progress bar and status when done
    progress_bar.empty()
    status_text.empty()
    

# === REGEX EXTRACTION ===

def advanced_duplicates_text_regex(duplicates_text: str) -> list:
    """
    Called by the "Process Duplicates" button.
    
    Advanced regex processing for duplicates text.
    
    Parameters:
    - duplicates_text (str): The raw duplicates message text to process
    
    Returns:
    - List of dictionaries containing extracted LEI data and metadata
    """
    block_re = re.compile(
        r'(?ms)^(?P<lei>[0-9A-Z]{20})\n(?P<rest>.*?)(?=\n{2,}[0-9A-Z]{20}\n|\Z)'
    )

    status_re = re.compile(r'(?m)^(ISSUED|LAPSED|PENDING_VALIDATION)$')
    zip_re = re.compile(r'(?m)^([A-Z0-9 -]+),.*\(legal address\)$')
    pair_re = re.compile(
        r'(?m)(?:^|\n)(?P<registration>[^\n]+?),\s*(?P<authority>RA\d{6})(?=,|\s*-|\n|$)'
    )

    results = []

    for m in block_re.finditer(duplicates_text):
        lei = m.group("lei")
        block = lei + "\n" + m.group("rest")
        lines = block.splitlines()

        company = lines[1].strip() if len(lines) > 1 else None

        status_match = status_re.search(block)
        status = status_match.group(1) if status_match else None

        zip_match = zip_re.search(block)
        zip_code = zip_match.group(1).strip() if zip_match else None

        # Only search registration pairs in the section between company and status
        reg_section = block
        if status_match:
            reg_section = block.split(status, 1)[0]

        pairs = []
        for pm in pair_re.finditer(reg_section):
            reg_id = re.sub(r'\s+', ' ', pm.group("registration")).strip()
            auth_id = pm.group("authority")
            # skip accidental capture of LEI/company if needed
            if reg_id != lei and reg_id != company:
                pairs.append({
                    "registration_id": reg_id,
                    "authority_id": auth_id
                })

        first_registration_id = pairs[0]["registration_id"] if pairs else None
        first_authority_id = pairs[0]["authority_id"] if pairs else None
        other_pairs = pairs[1:] if len(pairs) > 1 else []

        insufficient_regex_info = first_authority_id is None

        results.append({
            "lei": lei,
            "company_name": company,
            "registration_id": first_registration_id,
            "authority_id": first_authority_id,
            "other_registration_pairs": other_pairs,
            "status": status,
            "zip_code": zip_code,
            "insufficient_regex_info": insufficient_regex_info
        })
    
    st.session_state.results_duplicates_regex = results

    # Debug:
    #for company in results:
        #print(company)

    return results


# === LEI MANAGER EXTRACTION ===

def extract_lei_manager_vars(text_lei_manager: str, debug: bool = False) -> dict:

    """
    Called by the "Process LEI Manager" button.
    
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
    authority_id_pattern = r"Validation Authority ID:.*?\(\s*(RA\d{6})\s*\)"
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


# === AUTHORITY MATCHING ===

def authority_ID_check(gleif_authority_ID: str, manager_authority_ID: str) -> float:
    """
    Called by the "Check Duplicates" button (through the find_best_authority_match function).
    """
    if gleif_authority_ID in {"RA777777", "RA888888", "RA999999"} or manager_authority_ID in {"RA777777", "RA888888", "RA999999"}:
        return 50  # N/A, não é possível comparar
    authority_ID_score = fuzz.ratio(gleif_authority_ID, manager_authority_ID)
    if authority_ID_score == 100:
        return authority_ID_score # returns 100 if they are the same
    elif authority_ID_score is not None and authority_ID_score < 100:
        return 0
    return 0  # Fallback: return 0 if score is None or any other case
    
def find_best_authority_match(gleif_authority_pairs: list, manager_authority_pairs: list, manager_jurisdiction: str | None) -> tuple:
    """
    Called by the "Check Duplicates" button (through the generate_results function).
    Note: 
        In some cases where we have multiple MANAGER authorities, the table will
        show a score of 100, but you will see that the authority IDs don't match.
        This is because for every gleif candidate that goes through this function,
        we change what the MANAGER authority is. So, the program is working fine,
        but this will look a little weird. Too complicated to fix right now, maybe
        in the future.
    """
    if not gleif_authority_pairs or not manager_authority_pairs:
        return None, None, None, None

    # Start with first result from each list as baseline
    best_gleif_pair = gleif_authority_pairs[0]
    best_manager_pair = manager_authority_pairs[0]

    best_authority_score = authority_ID_check(best_gleif_pair["authority_ID"], best_manager_pair["authority_ID"])
    best_reg_ID_score = _calculate_reg_ID_score(best_gleif_pair.get("reg_ID"), best_manager_pair.get("reg_ID"))

    if best_authority_score != 100:
        for gleif_pair in gleif_authority_pairs:
            for manager_pair in manager_authority_pairs:
                current_authority_score = authority_ID_check(gleif_pair["authority_ID"], manager_pair["authority_ID"])
                if current_authority_score == 100:
                    current_reg_ID_score = _calculate_reg_ID_score(gleif_pair.get("reg_ID"), manager_pair.get("reg_ID"))
                    best_reg_ID_score = current_reg_ID_score
                    best_authority_score = current_authority_score
                    best_gleif_pair = gleif_pair
                    best_manager_pair = manager_pair

    if manager_jurisdiction in JURISDICTION_HANDLERS:
        config = JURISDICTION_HANDLERS[manager_jurisdiction]
        best_authority_score = config["function"]()
    
    return best_gleif_pair, best_manager_pair, best_authority_score, best_reg_ID_score


# === SCORE CALCULATION HELPERS ===

def _calculate_legal_name_score(gleif_name: str | None, manager_name: str | None) -> float | None:
    """Calculates fuzzy match score for legal names."""
    if not gleif_name or not manager_name:
        return None
    return fuzz.ratio(str(gleif_name).lower(), str(manager_name).lower())


def _calculate_address_score(gleif_addr: str | None, manager_addr: str | None) -> float | None:
    """
    Calculates address match score using both partial_ratio and token_set_ratio,
    returning the maximum of the two.
    """
    if not gleif_addr or not manager_addr:
        return None
    
    gleif_lower = str(gleif_addr).lower()
    manager_lower = str(manager_addr).lower()
    
    partial = fuzz.partial_ratio(gleif_lower, manager_lower)
    token_set = fuzz.token_set_ratio(gleif_lower, manager_lower)
    
    return max(partial, token_set)


def _calculate_date_score(gleif_date, manager_date) -> int | None:
    """Calculates date match score as absolute difference in days."""
    if not gleif_date or not manager_date:
        return None
    return abs((gleif_date.date() - manager_date).days)


def _calculate_legal_form_score(gleif_legal_form: str | None, gleif_legal_form_short: str | None, 
                               gleif_legal_form_other: str | None, manager_form: str | None) -> float | None:
    """
    Calculates legal form match score by comparing manager form against
    all three gleif legal form variants, returning the maximum score.
    """
    if not manager_form:
        return None
    
    manager_lower = str(manager_form).lower().strip()
    scores = []
    
    if gleif_legal_form:
        scores.append(fuzz.partial_ratio(str(gleif_legal_form).lower(), manager_lower))
    if gleif_legal_form_short:
        scores.append(fuzz.partial_ratio(str(gleif_legal_form_short).lower(), manager_lower))
    if gleif_legal_form_other:
        scores.append(fuzz.partial_ratio(str(gleif_legal_form_other).lower(), manager_lower))
    
    return max(scores) if scores else None


def _calculate_zipcode_score(gleif_zip: str | None, manager_zip: str | None) -> float | None:
    """Calculates zipcode match score."""
    if not gleif_zip or not manager_zip:
        return None
    return fuzz.ratio(str(gleif_zip), str(manager_zip))


def _calculate_reg_ID_score(gleif_reg_id: str | None, manager_reg_id: str | None) -> float | None:
    """
    Calculates registration ID match score using multiple scoring methods
    and returns the highest score.
    
    Methods used (in priority order):
    1. Substring check (100 if one is contained in the other)
    2. fuzz.ratio() - character-level similarity
    3. fuzz.partial_ratio() - best matching substring
    4. fuzz.token_set_ratio() - tokenized comparison
    
    Returns the maximum score from all methods.
    """
    if not gleif_reg_id or not manager_reg_id:
        return None
    
    gleif_clean = str(gleif_reg_id).replace(" ", "")
    manager_clean = str(manager_reg_id).replace(" ", "")
    
    scores = []
    
    # Method 1: Substring check (bidirectional)
    if gleif_clean in manager_clean or manager_clean in gleif_clean:
        scores.append(100)
    
    # Method 2: Standard fuzzy ratio
    scores.append(fuzz.ratio(gleif_clean, manager_clean))
    
    # Method 3: Partial ratio (better for substrings)
    scores.append(fuzz.partial_ratio(gleif_clean, manager_clean))
    
    # Method 4: Token set ratio (good for multi-part IDs)
    scores.append(fuzz.token_set_ratio(gleif_clean, manager_clean))
    
    return max(scores)


def _apply_special_authority_handlers(authority_id: str, gleif_reg_id: str | None, 
                                     manager_reg_id: str | None, current_score: float | None) -> float | None:
    """
    Applies special handling rules for specific authorities (e.g., India GST/PAN).
    Returns modified score if authority has a handler, otherwise returns original score.
    """
    if authority_id not in AUTHORITY_HANDLERS:
        return current_score
    
    handler_func = AUTHORITY_HANDLERS[authority_id]
    return handler_func(gleif_reg_id, manager_reg_id, current_score)


# === RESULTS & CLASSIFICATION ===

def generate_results() -> list:
    """
    Called by the "Check Duplicates" button.
    
    Compares all gleif duplicates against manager variables and generates
    similarity scores for each field. Returns list of result dicts with scores.
    """
    st.session_state.all_results = []
    all_results = []
    manager_vars = st.session_state.manager_vars
    all_gleif_duplicates = st.session_state.all_gleif_duplicates

    for duplicate in all_gleif_duplicates:
        gleif_variables = duplicate
        
        # Find best authority match across all authority pairs
        gleif_authority_pairs = gleif_variables.get("authority_pairs", [])
        manager_authority_pairs = manager_vars.get("authority_pairs", [])

        best_gleif_pair, best_manager_pair, authority_ID_score, reg_ID_score = find_best_authority_match(
            gleif_authority_pairs, 
            manager_authority_pairs, 
            manager_vars.get("jurisdiction")
        )

        # Update manager and gleif variables with best matching pair
        manager_vars["authority_ID"] = best_manager_pair["authority_ID"] if best_manager_pair else manager_vars["authority_ID"]
        manager_vars["reg_ID"] = best_manager_pair["reg_ID"] if best_manager_pair else manager_vars["reg_ID"]
        gleif_variables["authority_ID"] = best_gleif_pair["authority_ID"] if best_gleif_pair else gleif_variables["authority_ID"]
        gleif_variables["reg_ID"] = best_gleif_pair["reg_ID"] if best_gleif_pair else gleif_variables["reg_ID"]
        
        # Apply special authority handlers (e.g., India GST/PAN)
        if manager_vars["authority_ID"]:
            reg_ID_score = _apply_special_authority_handlers(
                manager_vars["authority_ID"],
                gleif_variables.get("reg_ID"),
                manager_vars.get("reg_ID"),
                reg_ID_score
            )

        # Calculate all field scores
        legal_name_score = _calculate_legal_name_score(
            gleif_variables.get("legal_name"),
            manager_vars.get("legal_name")
        )
        
        address_score = _calculate_address_score(
            gleif_variables.get("address"),
            manager_vars.get("address")
        )
        
        date_score = _calculate_date_score(
            gleif_variables.get("date"),
            manager_vars.get("date")
        )
        
        legal_form_score = _calculate_legal_form_score(
            gleif_variables.get("legal_form"),
            gleif_variables.get("legal_form_short"),
            gleif_variables.get("legal_form_other"),
            manager_vars.get("legal_form")
        )
        
        zipcode_score = _calculate_zipcode_score(
            gleif_variables.get("zipcode"),
            manager_vars.get("zipcode")
        )

        # Compile results
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
    return all_results


# === UI & DISPLAY ===

def is_streamlit_running() -> bool:
    try:
        return get_script_run_ctx() is not None
    except:
        return False


def get_feature_row_color(feature: str, value: float | None) -> str:
    """
    Called by the "Check Duplicates" button (through the build_comparison_table function).
    """
    if value is None:
        # Return yellow for missing critical data
        if feature in ["Creation Date", "ZIP Code", "Registration ID", "Address"]:
            return "background-color: #ffeb9c"  # amarelo
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


def build_comparison_table(results: dict, gleif_vars: dict, manager_vars: dict):
    """
    Called by the "Check Duplicates" button.
    """
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

def plot_scores(scores_list: dict | list, title: str = "Feature Similarity Scores") -> None:

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


# === CLASSIFICATION OVERRIDES ===

def apply_classification_overrides(base_color: str, scores: dict, gleif_vars: dict, manager_vars: dict) -> str:
    """
    Applies all registered CLASSIFICATION_OVERRIDE_RULES in order.
    Each rule may return a new color to override; returning None means no change.
    Rules are chained: each rule sees the color produced by the previous one.
    Returns the final color after all rules have been applied.
    """
    color = base_color
    for rule in CLASSIFICATION_OVERRIDE_RULES:
        result = rule(color, scores, gleif_vars, manager_vars)
        if result is not None:
            color = result
    return color


# === CHECK DUPLICATES LOGIC ===

def classify_candidate_emoji_color(results: dict) -> str:
    """
    Called by the "Check Duplicates" button.
    
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
    #if legal_name is None or address is None:
    #    return "UNKNOWN"

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


# === CHECK DUPLICATES BUTTON HELPERS ===

def _classify_all_results(all_results: list) -> dict:
    """
    Classifies all results by iterating through and categorizing each.
    Returns dict with: red_leis, yellow_leis, authority_mismatch, mismatched_leis.
    """
    classification = {
        "red_leis": [],
        "yellow_leis": [],
        "has_authority_mismatch": False,
        "mismatched_leis": [],
        "status_log": []
    }
    
    processed_leis = st.session_state.processed_leis
    all_gleif_duplicates = st.session_state.all_gleif_duplicates
    manager_vars = st.session_state.manager_vars
    
    for i, results in enumerate(all_results):
        authority_id_score = results.get("Authority ID")
        
        # Check for authority mismatch
        if authority_id_score == 0:
            classification["has_authority_mismatch"] = True
            classification["mismatched_leis"].append(processed_leis[i])
        
        # Classify status (base), then apply override rules
        gleif_vars = all_gleif_duplicates[i] if i < len(all_gleif_duplicates) else {}
        base_status = classify_candidate_emoji_color(results)
        status = apply_classification_overrides(base_status, results, gleif_vars, manager_vars)
        classification["status_log"].append(status)
        
        if status == "RED":
            classification["red_leis"].append(processed_leis[i])
        elif status == "YELLOW" or status == "UNKNOWN":
            classification["yellow_leis"].append(processed_leis[i])
    
    return classification


def _build_status_messages(classification: dict) -> dict:
    """
    Builds all status messages based on classification results.
    Returns dict with message keys: error_msg, yellow_msg, skipped_msg, authority_msg, success_msg (all optional/None).
    """
    messages = {
        "error_msg": None,
        "yellow_msg": None,
        "skipped_msg": None,
        "authority_msg": None,
        "success_msg": None
    }
    
    # RED duplicates alert
    if classification["red_leis"]:
        error_msg = "🔴 **DUPLICATE ALERT:** The following LEIs are flagged as likely duplicates:\n\n"
        for lei in classification["red_leis"]:
            error_msg += f"- {lei}\n"
        messages["error_msg"] = error_msg
    
    # YELLOW possible duplicates
    if classification["yellow_leis"]:
        warning_msg = ".🟡 **Possible duplicates found.** The following candidates require review:\n\n"
        for lei in classification["yellow_leis"]:
            warning_msg += f"- {lei}\n"
        messages["yellow_msg"] = warning_msg
    
    # Skipped LEIs
    if st.session_state.was_a_lei_skipped:
        warning_msg = ".⚠️ **Skipped LEIs.** The following LEIs could not be fetched and **must be reviewed manually:** \n\n"
        for skipped_lei_info in st.session_state.skipped_leis:
            lei = skipped_lei_info["lei"]
            status = skipped_lei_info["status"]
            error_code = skipped_lei_info["error_code"]
            
            if status == "PENDING_VALIDATION":
                warning_msg += f"- {lei} — {status}\n"
            else:
                warning_msg += f"- {lei} ({error_code})\n"
        messages["skipped_msg"] = warning_msg
    
    # Authority mismatch warning
    if classification["has_authority_mismatch"]:
        warning_msg = ".⚠️ **Authority Mismatch.** The following candidates have a **different Registration Authority ID.** These should be checked individually:\n\n"
        for lei in classification["mismatched_leis"]:
            warning_msg += f"- {lei}\n"
        messages["authority_msg"] = warning_msg
    
    # Success message (only if nothing else)
    if (not classification["red_leis"] and not classification["yellow_leis"] 
        and not classification["has_authority_mismatch"] and not st.session_state.was_a_lei_skipped):
        messages["success_msg"] = "🟢 No duplicates found! You may approve the order. See below for more details."
    
    return messages

def clean_copied_text(text: str) -> str:
    
    text = text.replace("*", "")
    if text.startswith("."):
        text = text[1:].strip()

    return text

def _display_status_messages(messages: dict) -> None:
    """Displays all status messages using appropriate Streamlit functions."""
    
    if messages["error_msg"]:
        st.error(messages["error_msg"])
        clean_text = clean_copied_text(messages["error_msg"])
        copy_button(clean_text)
    
    # Combine all warnings into a single message
    combined_warnings = []
    if messages["yellow_msg"]:
        combined_warnings.append(messages["yellow_msg"])
    if messages["skipped_msg"]:
        combined_warnings.append(messages["skipped_msg"])
    if messages["authority_msg"]:
        combined_warnings.append(messages["authority_msg"])
    
    if combined_warnings:
        text_to_display = "\n\n".join(combined_warnings)
        st.warning(text_to_display, icon = None)
        clean_text = clean_copied_text(text_to_display)
        copy_button(clean_text)
    
    if messages["success_msg"]:
        st.success(messages["success_msg"])
        clean_text = clean_copied_text(messages["success_msg"])
        copy_button(clean_text)


def _display_candidate_details(classification: dict) -> None:
    """
    Displays detailed comparison for each candidate in expandable sections.
    Uses status_log to determine emoji and authority warning.
    """
    processed_leis = st.session_state.processed_leis
    all_results = st.session_state.all_results
    all_gleif_duplicates = st.session_state.all_gleif_duplicates
    status_log = classification["status_log"]
    
    emoji_map = {
        "GREEN": "🟢",
        "YELLOW": "🟡",
        "RED": "🔴",
        "UNKNOWN": "🟡"
    }
    
    for i, results in enumerate(all_results):
        status = status_log[i]
        emoji = emoji_map[status]
        
        gleif_vars = all_gleif_duplicates[i]
        lei_code = processed_leis[i]
        
        # Check if Authority ID is 0 (different)
        authority_warning = " ⚠️ DIFFERENT AUTHORITY" if results.get("Authority ID") == 0 else ""

        with st.expander(f"{emoji} Duplicate candidate: {lei_code}{authority_warning}"):
            st.markdown(f"[View full record on GLEIF →](https://search.gleif.org/#/record/{lei_code})")
            styled_table = build_comparison_table(
                results,
                gleif_vars,
                st.session_state.manager_vars
            )
            st.dataframe(styled_table)


# === PROCESS DUPLICATES BUTTON HELPERS ===

def _extract_leis_from_duplicates_text(duplicates_text: str) -> list:
    """
    Extracts all LEIs from duplicates text using regex pattern.
    Removes duplicates while preserving order.
    """
    extracted_leis = re.findall(pattern, duplicates_text, flags=re.MULTILINE)
    # Remove duplicates while preserving order
    return list(dict.fromkeys(extracted_leis))


def _extract_lei_status_pairs(duplicates_text: str) -> dict:
    """
    Extracts LEI-Status pairs (ISSUED, PENDING_VALIDATION, LAPSED) from duplicates text.
    Uses a block-based approach to find statuses within their respective LEI blocks.
    """
    # Pattern to split into blocks - separated by double newlines
    block_re = re.compile(
        r'(?ms)^(?P<lei>[0-9A-Z]{20})\n(?P<rest>.*?)(?=\n{2,}[0-9A-Z]{20}\n|\Z)'
    )
    
    # Pattern to find status within a block - must be on its own line
    status_re = re.compile(r'(?m)^(ISSUED|PENDING_VALIDATION|LAPSED)$')
    
    lei_status_pairs = {}
    
    for m in block_re.finditer(duplicates_text):
        lei = m.group("lei")
        block = lei + "\n" + m.group("rest")
        
        # Search for status within this block only
        status_match = status_re.search(block)
        status = status_match.group(1) if status_match else None
        
        lei_status_pairs[lei] = status
    
    return lei_status_pairs


def _check_and_warn_missing_leis(duplicates_text: str, extracted_leis: list) -> None:
    """
    Checks if duplicate count in message exceeds extracted LEIs.
    Displays warning if LEIs are missing.
    """
    duplicate_count_match = re.search(pattern_duplicate_count, duplicates_text)
    if not duplicate_count_match:
        return
    
    total_duplicates = int(duplicate_count_match.group(1))
    # Count LEIs found including duplicates (before deduplication)
    all_leis_matches = re.findall(pattern, duplicates_text, flags=re.MULTILINE)
    found_leis_count = len(all_leis_matches)
    
    if total_duplicates > found_leis_count:
        missing_leis_count = total_duplicates - found_leis_count
        st.session_state.missing_leis_count = missing_leis_count
        st.warning(
            f"**{missing_leis_count} LEI(s)** mentioned in the duplicate count were not found in the extracted list. "
            f"This may be due to formatting issues in the message. **Make sure to check the remaining LEI(s) as well.**"
        )
    else:
        st.session_state.missing_leis_count = None


def _display_found_leis(duplicate_leis: list, lei_status_pairs: dict) -> None:
    """
    Displays all found LEIs with their status (ISSUED, PENDING_VALIDATION, LAPSED).
    """
    st.success(f"{len(duplicate_leis)} LEI(s) found:")
    for lei in duplicate_leis:
        status = lei_status_pairs.get(lei)
        if status and status != "ISSUED":
            st.write(f"{lei} - {status}")
        else:
            st.write(lei)


def _process_duplicates_text(duplicates_text: str) -> None:
    """
    Main orchestrator for processing duplicates text.
    Validates input, extracts data, displays results, and fetches GLEIF data.
    """
    if not duplicates_text.strip():
        st.warning("Please paste some text first.")
        return
    
    # Extract and process duplicates
    advanced_duplicates_text_regex(duplicates_text)
    extracted_leis = _extract_leis_from_duplicates_text(duplicates_text)
    lei_status_pairs = _extract_lei_status_pairs(duplicates_text)
    
    # Store in session state
    st.session_state.duplicate_leis = extracted_leis
    st.session_state.lei_status_pairs = lei_status_pairs
    
    # Check for missing LEIs and warn if needed
    _check_and_warn_missing_leis(duplicates_text, extracted_leis)
    
    # Display results or error
    if st.session_state.duplicate_leis:
        _display_found_leis(st.session_state.duplicate_leis, lei_status_pairs)
        fetch_all_gleif_vars()
    else:
        st.warning("No LEI-Number found (duplicates)")


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
    _process_duplicates_text(duplicates_text)


st.subheader("LEI Manager Data")

manager_text = st.text_area(
    "Paste the LEI Manager full text here",
    height=300
)

if st.button("Process LEI Manager", use_container_width=True):
    
    text = """
    not_idented\n
    - idented\n
    - idented\n
    - idented\n
    not_idented\n
    - idented\n
    - idented\n
    - idented\n
    not_idented\n

    """   
    
    text2 = """
    not_idented
    \n- idented\n
    - even_more_idented\n
    - even_more_idented\n
    idented
    - even_more_idented\n
    - even_more_idented\n
    - even_more_idented\n
    idented\n
    """
    text3 = """
    not_idented\n
    not_idented (but in a box that can be copied. Box starts here)\n
    - idented (but in a box that can be copied.)\n
    - idented (but in a box that can be copied.)\n
    - idented (but in a box that can be copied.)\n
    not_idented (but in a box that can be copied.)\n
    - idented (but in a box that can be copied.)\n
    - idented (but in a box that can be copied. Box ends here)\n
    \n- idented\n
    not_idented\n
    """
    warning_text = """
    Warning (not in the box)\n
    In the box\n
    In the box\n
    In the box\n
    \n- This line triggers the copyable box for everything except the first line (this line is also outside of the box). It is triggered by: "backslash" + "n" + "- "\n
    not in the box\n
    """

    test_warning = """
    Warning\n 
    ⚠️ Authority Mismatch. The following candidates have a different Registration Authority ID. These should be checked individually:\n
    - 724500RQU8AJ9ML32G38\n
    \n-
    """
    #st.warning(test_warning)
    #st.warning(warning_text)
    #st.warning(text)
    #st.warning(text2)
    #st.warning(text3)
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
    # Orchestrates the full duplicate checking workflow:
    # 1. Generate comparison results
    # 2. Classify all results
    # 3. Build and display status messages
    # 4. Display detailed candidate comparisons
    
    st.write("Initializing duplicate check...")
    
    # Generate results (scores) and classify (🔴,🟡,🟢,⚠️)
    all_results = generate_results()
    classification = _classify_all_results(all_results)
    
    # Store session state for display
    st.session_state.red_labeled_duplicates = classification["red_leis"]
    st.session_state.yellow_labeled_duplicates = classification["yellow_leis"]
    st.session_state.different_authority_candidates = classification["mismatched_leis"]
    
    # Build and display messages
    messages = _build_status_messages(classification)
    _display_status_messages(messages)
    
    # Display detailed candidate information
    _display_candidate_details(classification)