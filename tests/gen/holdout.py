"""Frozen evaluation family. Changes require an explicitly versioned benchmark."""
HOLDOUT = {
    'first': ['Ishita', 'Pranav', 'Leela', 'Devendra'],
    'last': ['Hegde', 'Nair', 'Chopra', 'Dasgupta'],
    'villages': ['Kesarwadi', 'Surajkheda', 'Madhupalli'],
    'headers': ['beneficiary', 'years_old', 'gender', 'residence', 'telephone', 'healthid', 'admission', 'discharge', 'condition', 'narrative'],
    'note': 'Seen today: {name}; contact {phone}; BP 120/80. Tab Dolo 650 mg BD.',
    'date': '%Y-%m-%d',
    'json_key': 'encounters',
}
