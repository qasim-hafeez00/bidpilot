library(survey)
des <- svydesign(ids=~1, weights=~w, data=resp)
svymean(~satisfaction, des)
