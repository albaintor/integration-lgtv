"""
LG Setup fields.

:copyright: (c) 2026 by Albaintor
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

SETUP_DEVICE_FIELDS = [
    {
        "field": {"text": {"value": ""}},
        "id": "address",
        "label": {"en": "IP address", "fr": "Adresse IP"},
    }
]

SETUP_FIELDS = [
    {
        "field": {"text": {"value": ""}},
        "id": "mac_address",
        "label": {"en": "Mac address (wired)", "fr": "Adresse Mac (cablé)"},
    },
    {
        "field": {"text": {"value": ""}},
        "id": "mac_address2",
        "label": {"en": "Mac address (wifi)", "fr": "Adresse Mac (wifi)"},
    },
    {
        "field": {"text": {"value": "0.0.0.0"}},
        "id": "interface",
        "label": {
            "en": "Interface to use for magic packet",
            "fr": 'Interface à utiliser pour le "magic packet"',
        },
    },
    {
        "field": {"text": {"value": ""}},
        "id": "broadcast",
        "label": {
            "en": "Broadcast address to use for magic packet (blank by default)",
            "fr": "Plage d'adresse à utiliser pour le magic packet (vide par défaut)",
        },
    },
    {
        "id": "wolport",
        "label": {
            "en": "Wake on lan port",
            "fr": "Numéro de port pour wake on lan",
        },
        "field": {"number": {"value": 9, "min": 1, "max": 65535, "steps": 1, "decimals": 0}},
    },
    {
        "id": "test_wakeonlan",
        "label": {
            "en": "Test turn on your configured TV (through wake on lan, TV should be off since 15 minutes at "
            "least)",
            "fr": "Tester la mise en marche de votre TV (via wake on lan, votre TV doit être éteinte depuis au "
            "moins 15 minutes)",
        },
        "field": {"checkbox": {"value": False}},
    },
    {
        "id": "pairing",
        "label": {
            "en": "Regenerate the pairing key and test connection",
            "fr": "Régénérer la clé d'appairage et tester la connection",
        },
        "field": {"checkbox": {"value": False}},
    },
    {
        "id": "update_apps_list",
        "label": {
            "en": "Update apps list and re-register entities if necessary",
            "fr": "Maintenir la liste des apps à jour et enregistrer les entités à nouveau si nécessaire",
        },
        "field": {"checkbox": {"value": True}},
    },
    {
        "id": "log",
        "label": {
            "en": "Enable additional traces for debugging",
            "fr": "Activer les traces additionnalles pour l'analyse",
        },
        "field": {"checkbox": {"value": False}},
    },
]

TEST_SETUP_FIELDS = [
    {
        "id": "update_apps_list",
        "label": {
            "en": "Update apps list and re-register entities if necessary",
            "fr": "Maintenir la liste des apps à jour et enregistrer les entités à nouveau si nécessaire",
        },
        "field": {"checkbox": {"value": False}},
    },
    {
        "id": "log",
        "label": {
            "en": "Enable additional traces for debugging",
            "fr": "Activer les traces additionnalles pour l'analyse",
        },
        "field": {"checkbox": {"value": False}},
    },
]
