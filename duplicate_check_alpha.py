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


# ### Variable Declarations


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
        The application compares candidates from a duplicates message against LEI Manager data, using fuzzy matching to evaluate similarities across multiple features:
        - Registration IDs
        - Legal Names
        - Addresses
        - Creation Dates
        - Legal Forms
        - Registration Authorities
                    
        ### How to Use
                    
        1. **Process Duplicates**: Paste the duplicates message that pops up on the top right of the LEI Manager
        2. **Process LEI Manager**: Paste the full text from the LEI Manager for the company you're checking against
        3. **Check Duplicates**: Click to run the comparison and view results
        
        ### Results Interpretation
        
        - **🔴 RED**: Likely duplicate - high similarity detected
        - **🟡 YELLOW**: Possible duplicate - moderate similarity or authority mismatch
        - **🟢 GREEN**: Unlikely duplicate - low similarity
        
        ### Scoring
        
        - Scores range from 0-100. Values close to 100 indicate high similarity
        - Date differences are shown in days
        - Different Authority ID gets flagged (⚠️), since registration IDs from different authorities cannot be compared directly
        """)
    
    st.markdown("---")
    
    # Author Credit
    st.markdown("""
    <div style="text-align: center; font-size: 0.8rem; color: gray; margin-top: 2rem;">
    <p><strong>LEI Duplicate Checker</strong></p>
    <p>Antonio Cesar Berenguer (2026)</p>
    </div>
    """, unsafe_allow_html=True)


pattern = r'^[A-Z0-9]{20}$'
url_stem = "https://api.gleif.org/api/v1/lei-records/"

FEATURE_KEY_MAP = {
    "Authority ID": "authority_ID",
    "RegistrationID": "reg_ID",
    "Legal Name": "legal_name",
    "Address": "address",
    "Date (delta)": "date",   # usado só para exibição
    "Legal Form": "legal_form"
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

df_gleif_authority = load_gleif_authority()


@st.cache_data
def load_legal_form_dictionary():
    return pd.read_excel(
        os.path.join(DATA_DIR, "GLEIF_legal_form_dictionary.xlsx")
    )

df_legal_form = load_legal_form_dictionary()


def duplicate_check (lei: str):
    """
    Doesn't actually perform a duplicate check, 
    but retrieves all relevant information from GLEIF API for a given LEI, 
    and formats it in a way that can be easily compared to the LEI Manager data.
    
    :param lei: lei code to be checked for duplicates (20-character alphanumeric string)
    :type lei: str

    returns:
    - gleif_variables (dict): dicionário contendo as variáveis extraídas da API
    """

    gleif_variables = {}
    url = f"{url_stem}{lei}"
    #print(url)

    page = requests.get(url)
    if page.status_code != 200:
        print(f"\n\n ********** Error searching for LEI {lei} — status {page.status_code} ********** \n\n")
        st.write(f"\n\n ********** Error searching for LEI {lei} — status {page.status_code} ********** \n\n")
        return

    json_data = page.json()

    #aqui precisa formatar

    DEFAULT_DATE = datetime(1, 1, 1)

    gleif_date = json_data["data"]["attributes"]["entity"]["creationDate"]
    if gleif_date is None:
        gleif_date = DEFAULT_DATE
    else:
        gleif_date = datetime.fromisoformat(gleif_date).replace(tzinfo=None)
    gleif_variables["date"] = gleif_date


    # Aqui precisa do dicionario das authorities
    gleif_authority_ID = json_data["data"]["attributes"]["entity"]["registeredAt"]["id"]
    gleif_variables["authority_ID"] = gleif_authority_ID

    gleif_authority_temp = df_gleif_authority.loc[df_gleif_authority["Registration Authority Code"] == gleif_authority_ID, "Local name of organisation responsible for the Register"]
    gleif_authority_local_name= gleif_authority_temp.iloc[0] if not gleif_authority_temp.empty else None
    gleif_variables["authority_local_name"] = gleif_authority_local_name

    gleif_reg_ID = json_data["data"]["attributes"]["entity"]["registeredAs"]
    gleif_variables["reg_ID"] = gleif_reg_ID

    gleif_legal_name = json_data["data"]["attributes"]["entity"]["legalName"]["name"]
    gleif_variables["legal_name"] = gleif_legal_name

    gleif_address_dict = json_data["data"]["attributes"]["entity"]["legalAddress"]

    gleif_address = concat_address_fields(gleif_address_dict)
    gleif_variables["address"] = gleif_address

    gleif_legal_form_ID = json_data["data"]["attributes"]["entity"]["legalForm"]["id"]

    gleif_legal_form_temp = df_legal_form.loc[df_legal_form["ELF Code"] == gleif_legal_form_ID, "Entity Legal Form name Local name"]
    gleif_legal_form = gleif_legal_form_temp.iloc[0] if not gleif_legal_form_temp.empty else None

    # Safely extract legal form and its short name (handles empty fields like '8888' and '9999')
    legal_form_short_series = df_legal_form.loc[df_legal_form["ELF Code"] == gleif_legal_form_ID, "Abbreviations Local language"]
    gleif_legal_form_short = legal_form_short_series.iloc[0] if not legal_form_short_series.empty else None

    gleif_legal_form_other = json_data["data"]["attributes"]["entity"]["legalForm"]["other"]

    gleif_variables["legal_form"] = gleif_legal_form
    gleif_variables["legal_form_short"] = gleif_legal_form_short
    gleif_variables["legal_form_other"] = gleif_legal_form_other

    return gleif_variables


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

def run_duplicate_checks():
    """
    Runs duplicate checks for all LEIs found in the duplicates message, 
    and stores the results in session state.

    Important: the duplicate_check function doens't really perform a duplicate check!!
    This needs to be addressed in the future. 
    """
    st.session_state.all_gleif_duplicates = []
    duplicate_leis = st.session_state.duplicate_leis
    for lei in duplicate_leis:
        result = duplicate_check(lei)
        if result is not None:
            st.session_state.all_gleif_duplicates.append(result)


def parse_lei_manager(text_lei_manager, debug=False):

    """
    Extracts relevant information from the LEI Manager text and 
    stores it in a dictionary for easy comparison with GLEIF data.

    Parameters:
    - text_lei_manager (str): full text of the LEI Manager
    - debug (bool): if True, prints the extracted values

    Returns:
    - manager_vars (dict): dictionary containing all extracted variables
    """
    manager_vars = {}

    # Legal Name
    legal_name_match = re.search(
        r"Legal Name:\s*\([^\)]*\)\s*(.+?)\s*(?:\(|\n)",
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
    ra_entity_id_match = re.search(r"Registration Authority Entity ID:(.+)", text_lei_manager)
    manager_ra_entity_id = ra_entity_id_match.group(1).strip() if ra_entity_id_match else None
    manager_vars["reg_ID"] = manager_ra_entity_id

    # Authority ID (The authority itself)
    authority_ID_match = re.search(r"Registration Authority ID:.*?\(\s*([A-Z0-9]+)\s*\)", text_lei_manager)
    manager_authority_ID = authority_ID_match.group(1).strip() if authority_ID_match else None
    manager_vars["authority_ID"] = manager_authority_ID

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
    """
    Checks if the authority IDs from GLEIF and the LEI Manager match.
        -If they are the same: returns 100
        -If they are different: returns 0
        -If one of them is RA777777, RA888888 or RA999999: returns 50
    
    :param gleif_authority_ID: Description
    :param manager_authority_ID: Description
    """

    if gleif_authority_ID in {"RA777777", "RA888888", "RA999999"} or manager_authority_ID in {"RA777777", "RA888888", "RA999999"}:
        return 50  # N/A, não é possível comparar
    authority_ID_score = fuzz.ratio(gleif_authority_ID, manager_authority_ID)
    if authority_ID_score == 100:
        return authority_ID_score # returns 100 if they are the same
    elif authority_ID_score is not None and authority_ID_score < 100:
        return 0
    return 0  # Fallback: return 0 if score is None or any other case
    


def generate_results():

    st.session_state.all_results = []
    
    all_results = []
    manager_vars = st.session_state.manager_vars
    all_gleif_duplicates = st.session_state.all_gleif_duplicates

    for duplicate in all_gleif_duplicates:

        gleif_variables = duplicate

        legal_form_score = fuzz.partial_ratio(str(gleif_variables["legal_form"]).lower(), str(manager_vars["legal_form"]).lower().strip())
        legal_form_short_score = fuzz.partial_ratio(str(gleif_variables["legal_form_short"]).lower(), str(manager_vars["legal_form"]).lower().strip())
        legal_form_other_score = fuzz.partial_ratio(str(gleif_variables["legal_form_other"]).lower(), str(manager_vars["legal_form"]).lower().strip())

        authority_ID_score = authority_ID_check(str(gleif_variables["authority_ID"]), str(manager_vars["authority_ID"]))
        #authority_ID_score = fuzz.ratio(str(gleif_variables["authority_ID"]), str(manager_vars["authority_ID"])) if gleif_variables.get("authority_ID") and manager_vars.get("authority_ID") else None

        results = [
            ("Authority ID", authority_ID_score), # Not lower-cased, needs to be precise
            ("RegistrationID", fuzz.ratio(str(gleif_variables["reg_ID"]), str(manager_vars["reg_ID"]))), # Not lower-cased, needs to be precise
            ("Legal Name", fuzz.ratio(str(gleif_variables["legal_name"]).lower(), str(manager_vars["legal_name"]).lower())), # return best match between legal-name and trade-name 
            ("Date (delta)", abs(gleif_variables["date"].date()-manager_vars["date"]).days), # absolute date-difference in days
            ("Address", fuzz.partial_ratio(str(gleif_variables["address"].lower()), str(manager_vars["address"]).lower())), # lower-cased addresses 
            ("Legal Form", max(legal_form_score, legal_form_short_score, legal_form_other_score)),
            ]

        all_results.append(results)
        st.session_state.all_results = all_results
        st.session_state.gleif_variables = gleif_variables

    return all_results


def is_streamlit_running():
    try:
        return get_script_run_ctx() is not None
    except:
        return False


def score_color(feature, value):
    if value is None:
        return ""
    
    if feature == "Authority ID":
        if value == 0:
            return "background-color: #ffeb9c"   # amarelo se não for identico
        elif value == 100:
            return ""   # sem cor se for identico
        else:
            return ""   # sem cor para casos como RA777777, RA888888 ou RA999999

    if feature == "Date (delta)":
        if value <= 7:
            return "background-color: #ffc7ce"   # vermelho
        elif value <= 30:
            return "background-color: #ffeb9c"   # amarelo
        else:
            return "background-color: #c6efce"   # verde
    else:
        if value >= 90:
            return "background-color: #ffc7ce"
        elif value >= 70:
            return "background-color: #ffeb9c"
        else:
            return "background-color: #c6efce"


def build_comparison_table(results, gleif_vars, manager_vars):

    rows = []

    for feature, score in results:

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
        lambda row: [
            score_color(row["Feature"].split(" ⚠️")[0], float(row["Score"])),
            score_color(row["Feature"].split(" ⚠️")[0], float(row["Score"])),
            score_color(row["Feature"].split(" ⚠️")[0], float(row["Score"])),
            score_color(row["Feature"].split(" ⚠️")[0], float(row["Score"]))
        ],
        axis=1
    )

    return styled_df

def build_comparison_table_2(results, gleif_vars, manager_vars):

    rows = []

    for feature, score in results:

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
        lambda row: [
            score_color(row["Feature"].split(" ⚠️")[0], float(row["Score"])),
            score_color(row["Feature"].split(" ⚠️")[0], float(row["Score"])),
            score_color(row["Feature"].split(" ⚠️")[0], float(row["Score"])),
            score_color(row["Feature"].split(" ⚠️")[0], float(row["Score"]))
        ],
        axis=1
    )

    return styled_df

def build_comparison_table_3(results, gleif_vars, manager_vars):

    rows = []

    for feature, score in results:

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

    return df


def build_comparison_table_4(results, gleif_vars, manager_vars):

    rows = []

    for feature, score in results:

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
    df = df.T  # Transpose the dataframe

    def color_transposed_row(row):
        """Color each column based on its Score value"""
        colors = []
        for col in row.index:
            # col now represents the original row index (0, 1, 2, 3...)
            # We need to get the feature name and score from the transposed df
            feature = df.loc["Feature", col]
            score = df.loc["Score", col]
            # Strip warning emoji from feature name before passing to score_color
            base_feature = feature.split(" ⚠️")[0]
            colors.append(score_color(base_feature, float(score)))
        return colors

    styled_df = df.style.apply(color_transposed_row, axis=1)

    return styled_df

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
        if feature == "Date (delta)":
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


def classify_duplicate(results):
    """
    Classifies duplicate candidates based on their similarity scores for key features,
    using predefined thresholds to determine if they are 
        -likely duplicates (RED), 
        -possible duplicates (YELLOW), or 
        -unlikely duplicates (GREEN). 
    Retorna: GREEN, YELLOW ou RED
    """

    scores = {feature: score for feature, score in results}

    authority_ID = scores.get("Authority ID")
    reg_ID = scores.get("RegistrationID")
    legal_name = scores.get("Legal Name")
    address = scores.get("Address")
    legal_form = scores.get("Legal Form")
    date = scores.get("Date (delta)")

    # Se faltar algo essencial
    if legal_name is None or address is None or date is None:
        return "UNKNOWN"

    # =========================
    # 🔴 PROVÁVEL DUPLICATA
    # =========================
    if (
        address >= 80
        or (reg_ID is None or reg_ID >= 95)
    ):
        return "RED"

    # =========================
    # 🟡 POSSÍVEL DUPLICATA
    # =========================
    if (
        address >= 65
        or (reg_ID is None or reg_ID >= 80)
        or (authority_ID is not None and authority_ID == 0)
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

if st.button("Process duplicates"):
    if duplicates_text.strip():
        st.session_state.duplicate_leis = re.findall(
            pattern,
            duplicates_text,
            flags=re.MULTILINE
        )

        if st.session_state.duplicate_leis:
            st.success(f"{len(st.session_state.duplicate_leis)} LEI(s) found:")
            for lei in st.session_state.duplicate_leis:
                st.write(lei)

            run_duplicate_checks()
        else:
            st.warning("No LEI-Number found (duplicates)")
    else:
        st.warning("Please paste some text first.")


st.subheader("LEI Manager Data")

manager_text = st.text_area(
    "Paste the LEI Manager full text here",
    height=300
)

if st.button("Process LEI Manager"):
    
    if manager_text.strip():
        manager_vars = parse_lei_manager(manager_text)
        if manager_vars["legal_name"] is not None:
            st.success("LEI Manager information extracted successfully")
        else:
            # Usually the most common reason for this is the 
            # LEI Manager's languagenot being changed to english
            st.warning("Data not found. Check if your lei-manager is in english")

    else:
        st.warning("Please paste the LEI Manager text first.")


if st.button("Check Duplicates"):

    st.write("Initializing duplicate check...")
    all_results = generate_results()
    status_log = []
    findings = "No duplicates found! You may aprove the order. See below for more details."
    is_there_a_duplicate = False
    duplicate_leis = st.session_state.duplicate_leis
    all_gleif_duplicates = st.session_state.all_gleif_duplicates
    
    for i, results in enumerate(all_results):
        status = classify_duplicate(results)
        status_log.append(status)
        if status == "RED":
            findings = f"DUPLICATE ALERT: {duplicate_leis[i]}\n"
            is_there_a_duplicate = True
            st.error(findings)

    if not is_there_a_duplicate:
        for status in status_log:
            if status == "YELLOW":
                findings = "🟡 Possible duplicates found. Please review the details below before approving the order."
                st.warning(findings)
                is_there_a_duplicate = True
                break

        if not is_there_a_duplicate:
            st.success(findings)


    # Check if any candidate has a different authority ID
    has_authority_mismatch = False
    for results in all_results:
        authority_id_score = results[0][1] if results and results[0][0] == "Authority ID" else None
        if authority_id_score == 0:
            has_authority_mismatch = True
            break
    
    # Show single warning if any authority mismatches exist
    if has_authority_mismatch:
        st.warning("⚠️ **One or more candidates have a DIFFERENT Registration Authority ID.**  These should be checked individually.")


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
        authority_id_score = results[0][1] if results and results[0][0] == "Authority ID" else None
        authority_warning = " ⚠️ DIFFERENT AUTHORITY" if authority_id_score == 0 else ""

        with st.expander(f"{emoji} Duplicate candidate: {lei_code}{authority_warning}"):

            styled_table = build_comparison_table(
                results,
                gleif_vars,
                st.session_state.manager_vars
            )

            st.dataframe(styled_table, width="stretch")