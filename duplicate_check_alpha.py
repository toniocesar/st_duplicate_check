#!/usr/bin/env python
# coding: utf-8

# # Duplicate Check (LEI-Manager)

# In[2]:


# O file que estamos usando aqui é o Auftrag 850530


# ### Imports

# In[3]:


from bs4 import BeautifulSoup
import requests
import json
from datetime import datetime, timedelta
import pandas as pd
import re
import pyperclip
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


# ### Variable Declarations

# In[4]:


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


pattern = r'^[A-Z0-9]{20}$'
url_stem = "https://api.gleif.org/api/v1/lei-records/"

FEATURE_KEY_MAP = {
    "RegistrationID": "reg_ID",
    "Legal Name": "legal_name",
    "Address": "address",
    "Date (delta)": "date",   # usado só para exibição
    "Legal Form": "legal_form"
}


# ### Reading of dictionaries (later optimize this using cache for streamlit

# In[5]:


try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Estamos no Jupyter ou console interativo
    BASE_DIR = os.getcwd()

DATA_DIR = os.path.join(BASE_DIR, "data")

df_gleif_authority = pd.read_csv(
    os.path.join(DATA_DIR, "GLEIF_authority_dictionary.csv")
)

print(df_gleif_authority.head())


# In[6]:


#df_gleif_authority = pd.read_csv(r"C:\Users\AC\Documents\EQS\Automation Project\Dictionaries\GLEIF_authority_dictionary.csv")


# In[30]:


try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Estamos no Jupyter ou console interativo
    BASE_DIR = os.getcwd()

DATA_DIR = os.path.join(BASE_DIR, "data")

df_legal_form = pd.read_excel(
    os.path.join(DATA_DIR, "GLEIF_legal_form_dictionary.xlsx")
)


# In[8]:


#df_legal_form = pd.read_excel(r"C:\Users\AC\Documents\EQS\Automation Project\Dictionaries\GLEIF_legal_form_dictionary.xlsx") 


# ### Functions

# In[9]:


def duplicate_check (lei: str):

    gleif_variables = {}
    url = f"{url_stem}{lei}"
    print(url)

    page = requests.get(url)
    if page.status_code != 200:
        print(f"\n\n ********** Erro ao buscar LEI {lei} — status {page.status_code} ********** \n\n")
        st.write(f"\n\n ********** Error searching for LEI {lei} — status {page.status_code} ********** \n\n")
        return

    soup = BeautifulSoup(page.text, 'html')
    #print(f"DEBUG: str(soup): {str(soup)}")
    json_data = json.loads(str(soup))

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


# In[10]:


def concat_address_fields(address: dict) -> str:
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


# In[11]:


def run_duplicate_checks():
    st.session_state.all_gleif_duplicates = []
    for lei in st.session_state.duplicate_leis:
        result = duplicate_check(lei)
        if result is not None:
            st.session_state.all_gleif_duplicates.append(result)


# In[12]:


def parse_lei_manager(text_lei_manager, debug=False):

    """
    Extrai informações do texto do LEI Manager.

    Parâmetros:
    - text_lei_manager (str): texto completo do LEI Manager
    - debug (bool): se True, printa os valores extraídos

    Retorna:
    - manager_vars (dict): dicionário com todas as variáveis extraídas
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


# In[13]:


def generate_results():

    st.session_state.all_results = []
    all_results = []

    for duplicate in st.session_state.all_gleif_duplicates:

        gleif_variables = duplicate

        legal_form_score = fuzz.partial_ratio(str(gleif_variables["legal_form"]).lower(), str(st.session_state.manager_vars["legal_form"]).lower().strip())
        legal_form_short_score = fuzz.partial_ratio(str(gleif_variables["legal_form_short"]).lower(), str(st.session_state.manager_vars["legal_form"]).lower().strip())
        legal_form_other_score = fuzz.partial_ratio(str(gleif_variables["legal_form_other"]).lower(), str(st.session_state.manager_vars["legal_form"]).lower().strip())

        results = [
            ("RegistrationID", fuzz.ratio(str(gleif_variables["reg_ID"]), str(st.session_state.manager_vars["reg_ID"]))), # Not lower-cased, needs to be precise
            ("Legal Name", fuzz.ratio(str(gleif_variables["legal_name"]).lower(), str(st.session_state.manager_vars["legal_name"]).lower())), # return best match between legal-name and trade-name 
            ("Date (delta)", abs(gleif_variables["date"].date()-st.session_state.manager_vars["date"]).days), # absolute date-difference in days
            ("Address", fuzz.partial_ratio(str(gleif_variables["address"].lower()), str(st.session_state.manager_vars["address"]).lower())), # lower-cased addresses 
            ("Legal Form", max(legal_form_score, legal_form_short_score, legal_form_other_score)),
            ]

        all_results.append(results)
        st.session_state.all_results = all_results
        st.session_state.gleif_variables = gleif_variables

    return st.session_state.all_results


# In[14]:


def is_streamlit_running():
    try:
        return get_script_run_ctx() is not None
    except:
        return False


# In[29]:


def score_color(feature, value):
    if value is None:
        return ""

    if feature == "Date (delta)":
        if value <= 7:
            return "background-color: #c6efce"   # verde
        elif value <= 30:
            return "background-color: #ffeb9c"   # amarelo
        else:
            return "background-color: #ffc7ce"   # vermelho
    else:
        if value >= 90:
            return "background-color: #c6efce"
        elif value >= 70:
            return "background-color: #ffeb9c"
        else:
            return "background-color: #ffc7ce"


# In[28]:


def build_comparison_table(results, gleif_vars, manager_vars):

    rows = []

    for feature, score in results:

        manager_value = manager_vars.get(
            feature.lower().replace(" ", "_").replace("(delta)", "").strip(),
            None
        )

        gleif_value = gleif_vars.get(
            feature.lower().replace(" ", "_").replace("(delta)", "").strip(),
            None
        )

        rows.append({
            "Feature": feature,
            "LEI Manager": manager_value,
            "GLEIF Candidate": gleif_value,
            "Score": score
        })

    df = pd.DataFrame(rows)

    styled_df = df.style.apply(
        lambda row: [
            "",
            "",
            "",
            score_color(row["Feature"], row["Score"])
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

        rows.append({
            "Feature": feature,
            "LEI Manager": manager_value,
            "GLEIF Candidate": gleif_value,
            "Score": score
        })

    df = pd.DataFrame(rows)

    df = df.astype(str)

    styled_df = df.style.apply(
        lambda row: [
            "",
            "",
            "",
            score_color(row["Feature"], float(row["Score"]))
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

        rows.append({
            "Feature": feature,
            "LEI Manager": manager_value,
            "GLEIF Candidate": gleif_value,
            "Score": score
        })

    df = pd.DataFrame(rows)

    return df

def build_comparison_table_test_0(results):

    rows = []

    for feature, score in results:
        rows.append({
            "Feature": str(feature),
            "Score": float(score)
        })

    return pd.DataFrame(rows)



# In[15]:


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


# In[31]:


def classify_duplicate(results):
    """
    Classifica um duplicate usando todas as features disponíveis.
    Retorna: GREEN, YELLOW ou RED
    """

    scores = {feature: score for feature, score in results}

    reg_ID = scores.get("RegistrationID")
    legal_name = scores.get("Legal Name")
    address = scores.get("Address")
    legal_form = scores.get("Legal Form")
    date = scores.get("Date (delta)")

    # Se faltar algo essencial
    if legal_name is None or address is None or date is None:
        return "UNKNOWN"

    # =========================
    # 🟢 PROVÁVEL DUPLICATA
    # =========================
    if (
        legal_name >= 90
        and address >= 80
        and date <= 7
        and (reg_ID is None or reg_ID >= 95)
        and (legal_form is None or legal_form >= 80)
    ):
        return "GREEN"

    # =========================
    # 🟡 POSSÍVEL DUPLICATA
    # =========================
    if (
        legal_name >= 80
        and address >= 65
        and date <= 30
        and (reg_ID is None or reg_ID >= 80)
        and (legal_form is None or legal_form >= 60)
    ):
        return "YELLOW"

    # =========================
    # 🔴 POUCO PROVÁVEL
    # =========================
    return "RED"


# ### Insert Message Below

# In[16]:


if st.button("Reset Variables"):
    st.session_state.clear()


# In[17]:





# In[25]:


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


# In[ ]:





# In[19]:


#duplicate_leis = re.findall(pattern, duplicate_message, flags=re.MULTILINE)
#print(duplicate_leis)


# In[20]:


#len(duplicate_leis)


# ### Run Web Scraping (GLEIF Website)

# In[ ]:





# ### LEI-Manager Data-extraction

# In[26]:


st.subheader("LEI Manager Data")

manager_text = st.text_area(
    "Paste the LEI Manager full text here",
    height=300
)

if st.button("Process LEI Manager"):
    if manager_text.strip():
        st.session_state.manager_vars = parse_lei_manager(manager_text)

        if st.session_state.manager_vars["legal_name"] is not None:
            st.success("LEI Manager information extracted successfully")
        else:
            st.warning("Data not found. Check if your lei-manager is in english")

    else:
        st.warning("Please paste the LEI Manager text first.")



# ### Matching

# In[33]:


if st.button("Plot"):

    st.success("Plot button was pressed")

    all_results = generate_results()
    
    
    for i, results in enumerate(all_results):
        

        status = classify_duplicate(results)
        emoji = {
            "GREEN": "🟢",
            "YELLOW": "🟡",
            "RED": "🔴"
        }[status]

        
        gleif_vars = st.session_state.all_gleif_duplicates[i]
        lei_code = st.session_state.duplicate_leis[i]

        with st.expander(f"🔍{emoji} Duplicate candidate: {lei_code}"):

#            styled_table = build_comparison_table_3(
 #               results,
  #              gleif_vars,
   #             st.session_state.manager_vars
    #        )

            #st.dataframe(styled_table, use_container_width=True)
            #st.table(styled_table)
            df = build_comparison_table_test_0(results)
            st.table(df)



# In[ ]:




