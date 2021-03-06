#! /usr/bin/python3

from bsddb3 import db as berkeleyDB
import re
import datetime
import time
from csv import reader

# load up all four indicies/databases
reviewsDB = berkeleyDB.DB()
reviewsDB.open("rw.idx")

ptermsDB = berkeleyDB.DB()
ptermsDB.open("pt.idx")

rtermsDB = berkeleyDB.DB()
rtermsDB.open("rt.idx")

scoresDB = berkeleyDB.DB()
scoresDB.open("sc.idx")


class Query():
    """
    Represents a query, including all conditions

    The constructor parses a string and constructs lists
    of pterms, rterms, general terms, and conditions
    """
    def __init__(self, q):
        """
        Parse a query
        """
        self.pterms = []
        self.rterms = []
        self.generalterms = []

        self.ptermsSet = 0
        self.rtermsSet = 0
        self.generaltermsSet = 0
        
        # These lists represent the maximum and minimum
        # for the range conditions 
        # The absence of an upper or lower bound
        # is represented as None
        self.rscoreBounds = [None, None]
        self.rdateBounds = [None, None]
        self.ppriceBounds = [None, None]

        self.rscoreBoundsSet = 0

        # find pterm specifications
        m = re.findall(r'p:([a-z]+)', q)
        if m:
            self.pterms += m
        q = re.sub(r'p:[a-z]+', '', q)

        # find rterm specifications
        m = re.findall(r'r:([a-z]+)', q)
        if m:
            self.rterms += m
        q = re.sub(r'r:[a-z]+', '', q)

        # find bounds
        self.processBounds(re.findall(r'([a-z]+) ?([<>]) ?([0-9/]+)', q))
        q = re.sub(r'[a-z]+ ?[<>] ?[0-9/]+', '', q)

        # find general terms
        m = re.findall(r'[a-z%]+', q)
        if m:
            self.generalterms += m


    def processBounds(self, conditions):
        """
        Populate the Bounds tuples
        """
        for term, operator, bound in conditions:
            
            if term == 'rscore':
                bounds = self.rscoreBounds
            elif term == 'rdate':
                bounds = self.rdateBounds
            else:
                bounds = self.ppriceBounds

            if operator == "<":
                bounds[1] = bound
            else:
                bounds[0] = bound

# End of Query class

def processQuery(query):
    """
    Get the results in the database specified 
    by the query object
    """
        
    if query.generalterms:
        query.generaltermsSet = 1
    if query.pterms:
        query.ptermsSet = 1
    if query.rterms:
        query.rtermsSet = 1
    if query.rscoreBounds[0] or query.rscoreBounds[1]:
        query.rscoreBoundsSet = 1            


    ptermsResults = [processPterms(query.pterms)]
    rtermsResults = [processRterms(query.rterms)]
    generaltermsResults = [processGeneralTerms(query.generalterms)]

    # query results are 'AND'ed together 
    processRScoreTermsResults = []
    if query.rscoreBounds[0] or query.rscoreBounds[1]:
        processRScoreTermsResults = processRScoreTerms(scoresDB.cursor(), query.rscoreBounds[0],query.rscoreBounds[1])

    resultIDs = sum(ptermsResults + rtermsResults + generaltermsResults + [processRScoreTermsResults], [])
          
    allTermsResults = [(ptermsResults, query.ptermsSet), (rtermsResults, query.rtermsSet), (generaltermsResults, query.generaltermsSet), ([processRScoreTermsResults], query.rscoreBoundsSet)]
    for term, setCondition in allTermsResults:
        if setCondition:
            # http://stackoverflow.com/questions/642763/python-intersection-of-two-lists
            resultIDs = list(set(term[0]).intersection(resultIDs))

    allBounds = [["rdate", query.rdateBounds], ["pprice", query.ppriceBounds]]
    for [condition, bounds] in allBounds:
        if bounds[0] is not None or bounds[1] is not None:
            resultIDs = processConditionBounds(resultIDs, condition, bounds)

    displayResults(resultIDs)
    return sorted([int(i) for i in resultIDs])

def dateToTimeStamp(dateString):
    # Assumes date in the right format: %Y/%m/%d
    # http://stackoverflow.com/questions/9637838/convert-string-date-to-timestamp-in-python
    if dateString != None:
        return int(datetime.datetime.strptime(dateString, "%Y/%m/%d").timestamp())
    else:
        return None

def processConditionBounds(resultIDs, condition, bounds):
    [minValue, maxValue] = bounds;
    newResultIDs = []
    # uses reviewsDB
    index = 0
    if "price" in condition:
        index = 2 # corresponding to pprice
    elif "rdate" in condition:
        index = 7 # corresponding to time
        minValue = dateToTimeStamp(minValue)
        maxValue = dateToTimeStamp(maxValue)
    elif "rscore" in condition:
        index = 6 # corresponding to score
        
    for resultID in resultIDs: # loop over all matches/review ids
        data = getAllMatchingKeys(resultID, reviewsDB)
        for datum in data: 
            # loop over all results, displaying them one at a time
            datum = datum.decode()
            datumList = [d for d in reader([datum])][0]
            if "unknown" in datumList[index]:
                continue
            # both max and min present
            if (maxValue and minValue and float(minValue) < float(datumList[index]) < float(maxValue)):
                newResultIDs.append(resultID)
            elif (maxValue and not minValue and float(datumList[index]) < float(maxValue)):
                newResultIDs.append(resultID)
            elif (not maxValue and minValue and float(minValue) < float(datumList[index])):
                newResultIDs.append(resultID)                
    
    return newResultIDs

def wildCardSearches(dbCursor, stringUntilWildCard):
    masterKey = stringUntilWildCard

    if (type(masterKey) != bytes):
        masterKey = bytes(masterKey, encoding="utf-8")

    results = []
    returnValue = dbCursor.set_range(masterKey)
    if returnValue != None and masterKey in returnValue[0]:
        (key,value) = returnValue
        results = [value]
        while (masterKey in key and key != None and value != None):
            returnValue = dbCursor.next()
            if returnValue != None and masterKey in returnValue[0]:
                (key,value) = returnValue
                results.append(value)
            else:
                break;
    return results

def processRScoreTerms(dbCursor, minValue, maxValue):
    if not maxValue:
        maxValue = '1000'
    if not minValue:
        minValue = '-1';
    if (type(maxValue) != bytes):
        maxValue = bytes(maxValue, encoding="utf-8")
    if (type(minValue) != bytes):
        minValue = bytes(str(float(minValue) + 1), encoding="utf-8")

    results = []
    returnValue = dbCursor.set_range(minValue)
    if returnValue != None:
        (key,value) = returnValue
        if float(minValue) - 1 < float(returnValue[0]) < float(maxValue):
            results = [value]
        while (key != None and value != None):
            returnValue = dbCursor.next()
            if returnValue != None and float(minValue) - 1 < float(returnValue[0]) < float(maxValue):
                (key,value) = returnValue
                results.append(value)
            elif returnValue == None:
                break;
    return results

            
def displayResults(resultIDs):
    # for every id
    # display:
    # id, title, price, userid, profile name, helpfullness, review score, review timestamp, summary, and full text of review.

    # uses reviewsDB
    for resultID in resultIDs: # loop over all matches/review ids
        data = getAllMatchingKeys(resultID, reviewsDB)
        for datum in data: 
            # loop over all results, displaying them one at a time
            datum = datum.decode()
            datumList = [d for d in reader([datum])][0]
            print("product/productId: " + datumList[0])
            print("product/title: " + datumList[1])
            print("product/price: " + datumList[2])
            print("review/userId: " + datumList[3])
            print("review/profileName: " + datumList[4].replace("&quot;", '"'))
            print("review/helpfulness: " + datumList[5])
            print("review/score: " + datumList[6])
            print("review/time: " + datumList[7])
            print("review/summary: " + datumList[8].replace("&quot;", '"'))
            print("review/text: " + datumList[9].replace("&quot;", '"'))
            print()
    

def getAllMatchingKeys(masterKey, db):
    # http://stackoverflow.com/questions/12348346/berkeley-db-partial-match
    db_cursor = db.cursor()
    if (type(masterKey) != bytes):
        masterKey = bytes(masterKey, encoding="utf-8")

    (key,value) = db_cursor.get(masterKey, berkeleyDB.DB_SET_RANGE)
    results = []
    if (key == masterKey):
        results = [value]            
        while(key == masterKey and key != None and value != None):
            returnValue = db_cursor.get(masterKey, berkeleyDB.DB_NEXT)
            if (returnValue != None):
                (key,value) = returnValue
                if (key == masterKey):
                    results.append(value)
            else:
                break;
    return results
    
def processPterms(pterms):
    # uses ptermsDB
    resultIDs = []
    for pterm in pterms:
        # http://stackoverflow.com/questions/19511440/add-b-prefix-to-python-variable
        #resultIDs.append(getAllMatchingKeys(pterm, ptermsDB))
        resultIDs = sum([resultIDs] + [getAllMatchingKeys(pterm, ptermsDB)], [])
    return resultIDs

    

def processRterms(rterms):
    # uses rtermsDB
    resultIDs = []
    for rterm in rterms:
        # http://stackoverflow.com/questions/19511440/add-b-prefix-to-python-variable
        #resultIDs.append(getAllMatchingKeys(rterm, rtermsDB))
        resultIDs = sum([resultIDs] + [getAllMatchingKeys(rterm, rtermsDB)], [])
    return resultIDs

def processGeneralTerms(generalterms):
    # uses ptermsDB, rtermsDB
    resultIDs = sum([processRterms(generalterms)] + [processPterms(generalterms)], [])    
    for generalterm in generalterms:
        if "%" in generalterm:
            wildCardResultsRterms = wildCardSearches(rtermsDB.cursor(),generalterm[:-1])
            wildCardResultsPterms = wildCardSearches(ptermsDB.cursor(),generalterm[:-1])
            if len(wildCardResultsRterms) > 0:
                resultIDs = sum( [resultIDs] + [wildCardResultsRterms], [])
            if len(wildCardResultsPterms) > 0:
                resultIDs = sum( [resultIDs] + [wildCardResultsPterms], [])
                
    return resultIDs

def interface():
    """
    Basic UI to ask for queries
    """
    while True:
        q = input("Please input your query. Input 'q' to exit: ").lower()
        if q == 'q':
            break
        res = processQuery(Query(q))
        print()
        print(len(res), "review(s) were found that matched.")
        print("They were:", res)

    # close dbs before exiting
    reviewsDB.close()            
    ptermsDB.close()
    rtermsDB.close()
    scoresDB.close()            


if __name__=='__main__':
    interface()
