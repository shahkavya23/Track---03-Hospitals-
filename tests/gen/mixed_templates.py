"""Versioned disjoint templates for processable mixed-document generation."""

MIXED_TUNE = {
    "filename": "blended_discharge_note.txt",
    "opening": "Discharge narrative prepared after morning rounds.",
    "table": "| Measure | Reading |\n| Pulse | 72 |",
    "chat": "[12/08/24, 8:10 PM] {name}: medicine taken",
    "json_key": "patient_name",
}

MIXED_HOLDOUT = {
    "filename": "compound_release_memo.dat",
    "opening": "Release memorandum assembled after evening handover.",
    "table": "Test\tObserved\nHb\t10.4",
    "chat": "[2024-08-12 20:10] {name}: dose received",
    "json_key": "beneficiary_label",
}

EMAIL_OCR_TUNE = {
    "filename": "forwarded_discharge_thread.eml.txt",
    "doctor": "Dr. Kavita Kulkarni",
    "relative": "Rohan Kulkarni",
    "staff": "Sr. Mary",
    "deva_staff": "रीना जोशी",
    "urdu_rel": "علی خان",
    "festival": "Holi",
}

EMAIL_OCR_HOLDOUT = {
    "filename": "replied_summary_scan.eml.txt",
    "doctor": "Dr. Arvind Hegde",
    "relative": "Meenakshi Hegde",
    "staff": "Sr. Clara",
    "deva_staff": "सीमा वर्मा",
    "urdu_rel": "زینب بیگم",
    "festival": "Diwali",
}
