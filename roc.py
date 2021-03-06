
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import itertools
import statsmodels.api as sm
import sklearn
import sklearn.ensemble
import sklearn.cross_validation
import sklearn.linear_model
import palettable

sns.set(style='darkgrid', palette='muted', font_scale=1.5)

__all__ = ['computeROC',
           'computeCVROC',
           'computeLOOROC',
           'plotROC',
           'plotCVROC',
           'plotProb',
           'plot2Prob',
           'lassoVarSelect',
           'smLogisticRegression',
           'rocStats']

def computeROC(df, model, outcomeVar, predVars):
    """Apply model to df and return performance metrics.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain outcome and predictor variables.
    model : sklearn or other model
        Model must have fit and predict methods.
    outcomeVar : str
    predVars : ndarray or list
        Predictor variables in the model.

    Returns
    -------
    fpr : np.ndarray
        False-positive rate
    tpr : np.ndarray
        True-positive rate
    auc : float
        Area under the ROC curve
    acc : float
        Accuracy score
    results : returned by model.fit()
        Model results object for test prediction in CV
    prob : pd.Series
        Predicted probabilities with index from df"""

    if not isinstance(predVars, list):
        predVars = list(predVars)
    tmp = df[[outcomeVar] + predVars].dropna()

    try:
        results = model.fit(X=tmp[predVars].astype(float), y=tmp[outcomeVar].astype(float))
        if hasattr(results, 'predict_proba'):
            prob = results.predict_proba(tmp[predVars].astype(float))[:, 1]
        else:
            prob = results.predict(tmp[predVars].astype(float))
            results.predict_proba = results.predict
        fpr, tpr, thresholds = sklearn.metrics.roc_curve(tmp[outcomeVar].values, prob)

        acc = sklearn.metrics.accuracy_score(tmp[outcomeVar].values, np.round(prob), normalize=True)
        auc = sklearn.metrics.auc(fpr, tpr)
        tpr[0], tpr[-1] = 0, 1
    except sm.tools.sm_exceptions.PerfectSeparationError:
        print('PerfectSeparationError: %s (N = %d; %d predictors)' % (outcomeVar, tmp.shape[0], len(predVars)))
        acc = 1.
        fpr = np.zeros(5)
        tpr = np.ones(5)
        tpr[0], tpr[-1] = 0, 1
        prob = df[outcomeVar].values.astype(float)
        auc = 1.
        results = None
    assert acc <= 1
    return fpr, tpr, auc, acc, results, pd.Series(prob, index=tmp.index, name='Prob')

def computeCVROC(df, model, outcomeVar, predVars, nFolds=10):
    """Apply model to df and return performance metrics in a cross-validation framework.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain outcome and predictor variables.
    model : sklearn or other model
        Model must have fit and predict methods.
    outcomeVar : str
    predVars : ndarray or list
        Predictor variables in the model.
    nFolds : int
        N-fold cross-validation (not required for LOO)

    Returns
    -------
    fpr : np.ndarray
        Pre-specified vector of FPR thresholds for interpolation
        fpr = np.linspace(0, 1, 100)
    meanTPR : np.ndarray
        Mean true-positive rate in test fraction.
    auc : float
        Area under the mean ROC curve.
    acc : float
        Mean accuracy score in test fraction.
    results : returned by model.fit()
        Training model results object for each fold
    prob : pd.Series
        Mean predicted probabilities on test data with index from df
    success : bool
        An indicator of whether the cross-validation was completed."""

    if not isinstance(predVars, list):
        predVars = list(predVars)
    tmp = df[[outcomeVar] + predVars].dropna()
    cv = sklearn.cross_validation.KFold(n=tmp.shape[0],
                                        n_folds=nFolds,
                                        shuffle=True,
                                        random_state=110820)
    fpr = np.linspace(0, 1, 100)
    tpr = np.nan * np.zeros((fpr.shape[0], nFolds))
    acc = 0
    counter = 0
    results = []
    prob = []
    for i, (trainInd, testInd) in enumerate(cv):
        trainDf = tmp.iloc[trainInd]
        testDf = tmp.iloc[testInd]
        trainFPR, trainTPR, trainAUC, trainACC, res, trainProb = computeROC(trainDf,
                                                                            model,
                                                                            outcomeVar,
                                                                            predVars)
        if not res is None:
            counter += 1
            testProb = res.predict_proba(testDf[predVars].astype(float))[:, 1]
            testFPR, testTPR, _ = sklearn.metrics.roc_curve(testDf[outcomeVar].values, testProb)
            tpr[:, i] = np.interp(fpr, testFPR, testTPR)
            acc += sklearn.metrics.accuracy_score(testDf[outcomeVar].values, np.round(testProb), normalize=True)
            results.append(res)
            prob.append(pd.Series(testProb, index=testDf.index))
    
    if counter == nFolds:
        meanTPR = np.nanmean(tpr, axis=1)
        meanTPR[0], meanTPR[-1] = 0, 1
        meanACC = acc / counter
        meanAUC = sklearn.metrics.auc(fpr, meanTPR)
        """Compute mean probability over test predictions in CV"""
        probS = pd.concat(prob).groupby(level=0).agg(np.mean)
        probS.name = 'Prob'
        assert probS.shape[0] == tmp.shape[0]
        success = True
    else:
        print('ROC: did not finish all folds (%d of %d)' % (counter, nFolds))
        """If we get a PerfectSeparation error on one fold then report model fit to all data"""
        print("Returning metrics from fitting complete dataset (no CV)")

        testFPR, testTPR, meanAUC, meanACC, res, probS = computeROC(tmp,
                                                                    model,
                                                                    outcomeVar,
                                                                    predVars)
        meanTPR = np.interp(fpr, testFPR, testTPR)
        meanTPR[0], meanTPR[-1] = 0, 1
        results = [res]
        success = False
        '''
        meanTPR = np.nan * fpr
        meanTPR[0], meanTPR[-1] = 0,1
        meanACC = np.nan
        meanAUC = np.nan
        """Compute mean probability over test predictions in CV"""
        probS = np.nan
        '''
    assert meanACC <= 1
    return fpr, meanTPR, meanAUC, meanACC, results, probS, success

def computeLOOROC(df, model, outcomeVar, predVars):
    """Apply model to df and return performance metrics in a cross-validation framework.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain outcome and predictor variables.
    model : sklearn or other model
        Model must have fit and predict methods.
    outcomeVar : str
    predVars : ndarray or list
        Predictor variables in the model.

    Returns
    -------
    fpr : np.ndarray
        Pre-specified vector of FPR thresholds for interpolation
        fpr = np.linspace(0, 1, 100)
    tpr : np.ndarray
        Mean true-positive rate in test fraction.
    auc : float
        Area under the mean ROC curve.
    acc : float
        Mean accuracy score in test fraction.
    results : returned by model.fit()
        Training model results object for each fold
    prob : pd.Series
        Mean predicted probabilities on test data with index from df
    success : bool
        An indicator of whether the cross-validation was completed."""

    if not isinstance(predVars, list):
        predVars = list(predVars)
    tmp = df[[outcomeVar] + predVars].dropna()

    cv = sklearn.cross_validation.LeaveOneOut(n=tmp.shape[0])
    nFolds = tmp.shape[0]

    fpr = np.linspace(0, 1, 100)
    prob = np.nan * np.ones(tmp.shape[0])
    outcome = np.nan * np.ones(tmp.shape[0])
    ids = []
    results = []
    
    """Fit model to all the data for use in cases when there is perfect separation"""
    try:
        wholeRes = model.fit(X=tmp[predVars].astype(float), y=tmp[outcomeVar].astype(float))
        if not hasattr(wholeRes, 'predict_proba'):
            wholeRes.predict_proba = wholeRes.predict
        wholeProb = wholeRes.predict_proba(tmp[predVars].astype(float))[:, 1]
    except sm.tools.sm_exceptions.PerfectSeparationError:
        print('PerfectSeparationError on complete dataset: %s (N = %d; %d predictors)' % (outcomeVar, tmp.shape[0], len(predVars)))
        outcome = tmp[outcomeVar]
        prob = outcome
        results = [None] * tmp.shape[0]

        testFPR, testTPR, thresholds = sklearn.metrics.roc_curve(outcome, prob)
        tpr = np.interp(fpr, testFPR, testTPR)
        acc = 1
        auc = 1
        tpr[0], tpr[-1] = 0, 1

        probS = pd.Series(prob, index=tmp.index)
        probS.name = 'Prob'
        assert probS.shape[0] == tmp.shape[0]
        success = False
        return fpr, tpr, auc, acc, results, probS, success

    for i, (trainInd, testInd) in enumerate(cv):
        trainDf = tmp.iloc[trainInd]
        testDf = tmp.iloc[testInd]
        outcome[i] = testDf[outcomeVar].astype(float).iloc[0]
        ids.append(tmp.index[testInd[0]])
        try:
            res = model.fit(X=trainDf[predVars].astype(float), y=trainDf[outcomeVar].astype(float))
            results.append(res)
            if not hasattr(res, 'predict_proba'):
                res.predict_proba = res.predict
            prob[i] = res.predict_proba(testDf[predVars].astype(float))[0, 1]
        except sm.tools.sm_exceptions.PerfectSeparationError:
            print('PerfectSeparationError: %s (N = %d; %d predictors)' % (outcomeVar, tmp.shape[0], len(predVars)))
            prob[i] = wholeProb[i]
            results.append(None)
    
    testFPR, testTPR, thresholds = sklearn.metrics.roc_curve(outcome, prob)
    tpr = np.interp(fpr, testFPR, testTPR)
    acc = sklearn.metrics.accuracy_score(outcome, np.round(prob), normalize=True)
    auc = sklearn.metrics.auc(testFPR, testTPR)
    tpr[0], tpr[-1] = 0, 1

    probS = pd.Series(prob, index=ids)
    probS.name = 'Prob'
    assert probS.shape[0] == tmp.shape[0]
    success = True
    return fpr, tpr, auc, acc, results, probS, success

def plotCVROC(df, model, outcomeVar, predictorsList, predictorLabels=None, rocFunc=computeLOOROC, **rocKwargs):
    """Plot of multiple ROC curves using same model and same outcomeVar with
    different sets of predictors.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain outcome and predictor variables.
    model : sklearn or other model
        Model must have fit and predict methods.
    outcomeVar : str
    predictorsList : list
        List of lists of predictor variables for each model.
    predictorLabels : list
        List of labels for the models (optional)
    rocFunc : computeCVROC or computeROC or computeLOOROC
        Function for computing the ROC
    rocKwargs : kwargs
        Additional arguments for rocFunc"""
    
    if predictorLabels is None:
        predictorLabels = [' + '.join(predVars) for predVars in predictorsList]
    
    colors = palettable.colorbrewer.qualitative.Set1_8.mpl_colors

    fprList, tprList, labelList = [], [], []

    for predVarsi, predVars in enumerate(predictorsList):
        fpr, tpr, auc, acc, res, probS, success = rocFunc(df,
                                                         model,
                                                         outcomeVar,
                                                         predVars,
                                                         **rocKwargs)

        if success:
            label = '%s (AUC = %0.2f; ACC = %0.2f)' % (predictorLabels[predVarsi], auc, acc)
        else:
            label = '%s (AUC* = %0.2f; ACC* = %0.2f)' % (predictorLabels[predVarsi], auc, acc)
        labelList.append(label)
        fprList.append(fpr)
        tprList.append(tpr)
    plotROC(fprList, tprList, labelL=labelList)

def plotROC(fprL, tprL, aucL=None, accL=None, labelL=None, outcomeVar=''):
    if labelL is None and aucL is None and accL is None:
        labelL = ['Model %d' % i for i in range(len(fprL))]
    else:
        labelL = ['%s (AUC = %0.2f; ACC = %0.2f)' % (label, auc, acc) for label, auc, acc in zip(labelL, aucL, accL)]

    colors = palettable.colorbrewer.qualitative.Set1_8.mpl_colors

    plt.clf()
    plt.gca().set_aspect('equal')
    for i, (fpr, tpr, label) in enumerate(zip(fprL, tprL, labelL)):
        plt.plot(fpr, tpr, color=colors[i], lw=2, label=label)
    plt.plot([0, 1], [0, 1], '--', color='gray', label='Chance')
    plt.xlim([-0.05, 1.05])
    plt.ylim([-0.05, 1.05])
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    if outcomeVar == '':
        plt.title('ROC')
    else:
        plt.title('ROC for %s' % outcomeVar)
    plt.legend(loc="lower right")
    plt.show()

def plotProb(outcome, prob, **kwargs):
    """Scatter plot of probabilities for one ourcome.

    Parameters
    ----------
    outcome : pd.Series
    prob : pd.Series
        Predicted probabilities returned from computeROC or computeCVROC"""

    colors = palettable.colorbrewer.qualitative.Set1_3.mpl_colors

    tmp = pd.concat((outcome, prob), join='inner', axis=1)
    tmp = tmp.sort_values(by=[outcome.name, 'Prob'])
    tmp['x'] = np.arange(tmp.shape[0])
    
    plt.clf()
    for color, val in zip(colors, tmp[outcome.name].unique()):
        ind = tmp[outcome.name] == val
        lab = '%s = %1.0f (%d)' % (outcome.name, val, ind.sum())
        plt.scatter(tmp.x.loc[ind], tmp.Prob.loc[ind], label=lab, color=color, **kwargs)
    plt.plot([0, tmp.shape[0]], [0.5, 0.5], 'k--', lw=1)
    plt.legend(loc='upper left')
    plt.ylabel('Predicted Pr(%s)' % outcome.name)
    plt.ylim((-0.05, 1.05))
    plt.xlim(-1, tmp.shape[0])
    plt.show()

def plot2Prob(df, outcomeVar, prob, **kwargs):
    """Scatter plot of probabilities for two outcomes.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain two outcome variables.
    model : sklearn or other model
        Model must have fit and predict methods.
    outcomeVar : list
        Contains two outcomeVar for comparison
    prob : list
        Contains two pd.Series with predicted probabilities
        from computeROC or computeCVROC"""
    labels = {(0, 0):'Neither',
              (1, 1):'Both',
              (0, 1):'%s only' % outcomeVar[1],
              (1, 0):'%s only' % outcomeVar[0]}
    markers = ['o', 's', '^', 'x']
    colors = palettable.colorbrewer.qualitative.Set1_5.mpl_colors
    tmp = df[outcomeVar].join(prob[0], how='inner').join(prob[1], how='inner', rsuffix='_Y')

    plt.clf()
    plt.gca().set_aspect('equal')
    prodIter = itertools.product(tmp[outcomeVar[0]].unique(), tmp[outcomeVar[1]].unique())
    for color, m, val in zip(colors, markers, prodIter):
        valx, valy = val
        ind = (tmp[outcomeVar[0]] == valx) & (tmp[outcomeVar[1]] == valy)
        lab = labels[val] + ' (%d)' % ind.sum()
        plt.scatter(tmp.Prob.loc[ind], tmp.Prob_Y.loc[ind], label=lab, color=color, marker=m, **kwargs)
    plt.plot([0.5, 0.5], [0, 1], 'k--', lw=1)
    plt.plot([0, 1], [0.5, 0.5], 'k--', lw=1)
    plt.ylim((-0.05, 1.05))
    plt.xlim((-0.05, 1.05))
    plt.legend(loc='upper left')
    plt.ylabel('Predicted Pr(%s)' % outcomeVar[1])
    plt.xlabel('Predicted Pr(%s)' % outcomeVar[0])
    plt.show()

def lassoVarSelect(df, outcomeVar, predVars, nFolds=10, LOO=False, alpha=None):
    """Apply LASSO to df and return performance metrics,
    optionally in a cross-validation framework to select alpha.

    ROC metrics computed on all data.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain outcome and predictor variables.
    outcomeVar : str
    predVars : ndarray or list
        Predictor variables in the model.
    nFolds : int
        N-fold cross-validation (not required for LOO)
    LOO : bool
        Use leave-one-out cross validation instead of n-fold
    alpha : float
        Constant that multiplies the L1 term (aka lambda)
        Defaults to 1.0
        alpha = 0 is equivalent to OLS
        Use None to set to maximum value given by:
            abs(X.T.dot(Y)).max() / X.shape[0]

    Returns
    -------
    fpr : np.ndarray
        False-positive rate.
    meanTPR : np.ndarray
        True-positive rate.
    auc : float
        Area under the ROC curve.
    acc : float
        Sccuracy score
    results : returned by Lasso.fit()
        Model results object
    prob : pd.Series
        Predicted probabilities with index from df
    varList : list
        Variables with non-zero coefficients
    alpha : float
        Optimal alpha value using coordinate descent path"""
    if not isinstance(predVars, list):
        predVars = list(predVars)
    tmp = df[[outcomeVar] + predVars].dropna()
    if nFolds == 1 or not alpha is None:
        """Pre-specify alpha, no CV needed"""
        if alpha is None:
            """Use the theoretical max alpha (not sure this is right though)"""
            alpha = np.abs(tmp[predVars].T.dot(tmp[outcomeVar])).max() / tmp.shape[0]
        model = sklearn.linear_model.Lasso(alpha=alpha)
    else:
        if LOO:
            cv = sklearn.cross_validation.LeaveOneOut(n=tmp.shape[0])
        else:
            cv = nFolds
        model = sklearn.linear_model.LassoCV(cv=cv)# , alphas=np.linspace(0.001,0.1,50))
    results = model.fit(y=tmp[outcomeVar].astype(float), X=tmp[predVars].astype(float))

    if hasattr(model, 'alpha_'):
        optimalAlpha = model.alpha_
    else:
        optimalAlpha = model.alpha
    
    prob = results.predict(tmp[predVars].astype(float))
    fpr, tpr, thresholds = sklearn.metrics.roc_curve(tmp[outcomeVar].values, prob)
    acc = sklearn.metrics.accuracy_score(tmp[outcomeVar].values, np.round(prob), normalize=True)
    auc = sklearn.metrics.auc(fpr, tpr)
    varList = np.array(predVars)[results.coef_ != 0].tolist()
    probS = pd.Series(prob, index=tmp.index, name='Prob')
    return fpr, tpr, auc, acc, results, probS, varList, optimalAlpha

class smLogisticRegression(object):
    """A wrapper of statsmodels.GLM to use with sklearn interface"""
    def __init__(self, fit_intercept=True):
        self.fit_intercept = fit_intercept

    def fit(self, X, y):
        if self.fit_intercept:
            exog = sm.add_constant(X, has_constant='add')
        else:
            exog = X
        self.res = sm.GLM(endog=y, exog=exog, family=sm.families.Binomial()).fit()
        return self

    def predict_proba(self, X):
        prob = np.zeros((X.shape[0], 2))
        prob[:, 0] = 1 - self.predict(X)
        prob[:, 1] = self.predict(X)
        return prob

    def predict(self, X):
        if self.fit_intercept:
            exog = sm.add_constant(X, has_constant='add')
        else:
            exog = X
        pred = self.res.predict(exog)
        return pred
def rocStats(obs, pred, returnSeries=True):
    """Compute stats for a 2x2 table derived from
    observed and predicted data vectors

    Parameters
    ----------
    obs,pred : np.ndarray or pd.Series of shape (n,)

    Optionally return a series with quantities labeled.

    Returns
    -------
    sens : float
        Sensitivity (1 - false-negative rate)
    spec : float
        Specificity (1 - false-positive rate)
    ppv : float
        Positive predictive value (1 - false-discovery rate)
    npv : float
        Negative predictive value
    acc : float
        Accuracy
    OR : float
        Odds-ratio of the observed event in the two predicted groups.
    rr : float
        Relative rate of the observed event in the two predicted groups.
    nnt : float
        Number needed to treat, to prevent one case.
        (assuming all predicted positives were "treated")"""

    assert obs.shape[0] == pred.shape[0]

    n = obs.shape[0]
    a = (obs.astype(bool) & pred.astype(bool)).sum()
    b = (obs.astype(bool) & (~pred.astype(bool))).sum()
    c = ((~obs.astype(bool)) & pred.astype(bool)).sum()
    d = ((~obs.astype(bool)) & (~pred.astype(bool))).sum()

    sens = a / (a+b)
    spec = d / (c+d)
    ppv = a / (a+c)
    npv = d / (b+d)
    nnt = 1 / (a/(a+c) - b/(b+d))
    acc = (a + d)/n
    rr = (a / (a+c)) / (b / (b+d))
    OR = (a/b) / (c/d)

    if returnSeries:
        vec = [sens, spec, ppv, npv, nnt, acc, rr, OR]
        out = pd.Series(vec, name='ROC', index=['Sensitivity', 'Specificity', 'PPV', 'NPV', 'NNT', 'ACC', 'RR', 'OR'])
    else:
        out = (sens, spec, ppv, npv, nnt, acc, rr, OR)
    return out



