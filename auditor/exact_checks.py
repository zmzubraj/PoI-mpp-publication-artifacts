def check_constraints(response, max_words=None, must_include=None, must_not_include=None):
    words=response.split()
    if max_words is not None and len(words)>max_words: return False
    low=response.lower()
    for x in must_include or []:
        if x.lower() not in low: return False
    for x in must_not_include or []:
        if x.lower() in low: return False
    return True
