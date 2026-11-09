"""Trusted routing for personal mentor profile contact forms.

Do not accept email destinations from POST data. Only a server-approved profile
slug may select an address. This directory is intentionally limited to profiles
published in /en/our-team (and their /fa equivalents). Add new mentors here
only after they have a real published profile and a complete verified email.
"""

from typing import Optional, Tuple

# (Public display name, validated recipient email)
_PROFILE_MENTOR_RECIPIENTS = {
    'rasoul-moradimehr': ('Dr. Rasoul Moradimehr', 'Rasoul@novanestholding.com'),
    'majid-soltanzadeh': ('Dr. Majid Soltanzadeh', 'jobdata@gmail.com'),
    'arvin-radan': ('Dr. Arvin Radan', 'Info@radinsight.ca'),
    # The Radan alias is reserved for a second profile/card using this slug.
    'professor-radan': ('Professor Radan', 'Info@radinsight.ca'),
    'avesta-narimani': ('Dr. Avesta Narimani', 'Rasnarim@gmail.com'),
    'alireza-mobini': ('Dr. Alireza Mobini', 'ar_mobini2009@yahoo.com'),
    'pouya-azadeh': ('Dr. Pouya Azadeh', 'Pouyaazadeh36@gmail.com'),
    'mojtaba-fadaei': ('Dr. Mojtaba Fadaei', 'info@asiahitech.com'),
}


def profile_mentor_recipient(profile_slug: str) -> Optional[Tuple[str, str]]:
    """Resolve a mentor profile slug without consulting any user-supplied email."""
    return _PROFILE_MENTOR_RECIPIENTS.get(profile_slug)
