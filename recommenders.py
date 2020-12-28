from typing import List
from functools import lru_cache
import pandas as pd 
from pandas import DataFrame
import numpy as np
from scipy.spatial import distance
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
import warnings
warnings.filterwarnings('ignore')
import io
import requests
#TO DO: delete what you can up here after all is said and done?

class Recommender:
    """Class containing collaborative, content, hybrid weighted-average, and hybrid switching recommenders"""

    def __init__(self, inputdata: DataFrame, user_id_col: str, item_id_col: str,  title_col: str, rating_col: str = "rating", metadata_col: str = "metadata", binary: bool = False):
        """
        :param inputdata: dataframe
        :param user_id_col: column title for user ID
        :param item_id_col: column title for item ID
        :param rating_col: column title for ratings
        :param metadata_col: column title for metadata
        :param binary: whether the user data are binary (e.g., purchase data) or not (e.g., ratings data)
        """
        ###TO DO: delete title-to-item and item-to-title dictionaries
        ###TO DO: delete held_out_matrix_raw 
        ###TO DO: move construction of recommender-specific datasets to their appropriate subclasses;
        ###%%%%%%%%%wait -- does that mean TF-IDF will be re-executed everytime we call ContentRecommender? bad for taking all those AP@k's
        ###TO DO: break MAP_at_k into subfunctions, one for recording the various AP@k's and one for actually taking MAP@k
        ###TO DO: unify the form of all corr/cos methods and lift them up to Recommender class; have subclasses refer to it
        ###TO DO: get rid of base class method recommend_items? just call the subclasses themselves. weight/cutoff for recommend_items is silly
        ###%%%%%%%%%wait -- what would the user want?
        ###TO DO: hybrid recommenders shouldn't have parameters, but should instead just call the other recommenders

        ###%%%%%%%%%wait -- if we do all this, what's the form of these submethods? just an init and some code that executes? what's the point of having it be a subclass?
        
        self._inputdata: DataFrame = inputdata
        self._user: str = user_id_col
        self._item: str = item_id_col
        self._title: str = title_col
        self._rating: str = rating_col
        self._metadata: str = metadata_col

        #dictionaries mapping title to item, and item to title
        self._title_to_item = {}
        for i in range(1, len(self._inputdata)):
            self._title_to_item[self._inputdata[self._title][i]] = self._inputdata[self._item][i]
        self._item_to_title = {}
        for i in range(1, len(self._inputdata)):
            self._item_to_title[self._inputdata[self._item][i]] = self._inputdata[self._title][i]

        #matrix of user ratings of each item
        self._item_matrix: DataFrame = self._inputdata.pivot_table(index = self._user, columns = self._title, values = self._rating)

        #splitting the user-ratings matrix into training (90%) and test (10%)
        held_out_count = int(len(self._item_matrix)/10)
        self._held_out_matrix: DataFrame = self._item_matrix.loc[:held_out_count, :]
        self._held_out_matrix_raw: DataFrame =  self._held_out_matrix
        self._item_matrix: DataFrame = self._item_matrix.loc[(held_out_count+1):len(self._item_matrix), :]
        
        #fill missing values with average rating
        self._item_matrix.fillna(2.5, inplace = True)

        ###if ratings data, convert held out users' ratings to 1's if rating is greater than 4, else convert to 0 
        if not binary:
            self._held_out_matrix = pd.DataFrame(np.where(self._held_out_matrix.values >= 4, 1, 0), self._held_out_matrix.index)
            self._held_out_matrix.columns = self._item_matrix.columns

        #matrix with items as rows and with mean ratings and rating count as cols
        self._ratings = DataFrame(self._inputdata.groupby(self._title)['rating'].mean())
        self._ratings['Number_of_ratings'] = self._inputdata.groupby(self._title)['rating'].count()

        #creates non-latent matrix for content recommendation, then latent matrix by applying TF-IDF to metadata and then SVD to reduce dimensionality to 200 features
        self._cont_matrix: DataFrame = self._inputdata[[self._title, self._metadata]]
        self._cont_matrix.drop_duplicates(subset = self._title, inplace = True)
        tfidf = TfidfVectorizer(stop_words = "english")
        tfidf_matrix = tfidf.fit_transform(self._cont_matrix[self._metadata])
        tfidf_df = pd.DataFrame(tfidf_matrix.toarray(), index = self._cont_matrix.index.tolist())
        svd = TruncatedSVD(n_components = 200)
        latent_matrix_1 = svd.fit_transform(tfidf_df)
        self._latent_cont_matrix: DataFrame = pd.DataFrame(latent_matrix_1, index = self._cont_matrix[self._title].tolist()).transpose()
        self._cont_ratings: pd.Series = pd.Series(self._ratings['Number_of_ratings'][x] for x in self._latent_cont_matrix.columns)
        
    @lru_cache(maxsize = 1000)
    def recommend_items(self, item_name: str, distance_metric: str = "cos", approach: str = "collab", weight: float = 0.5, cutoff: int = 50) -> DataFrame:
        """
        returns ordered list of recommended items based on a given seed item
        :param item_name: name of item to use a seed
        :param distance_metric: method by which similarity is calculated
        :param approach: type of recommender used
        :param weight: weight to be fed into hybrid weighted-average recommender
        :param cutoff: switchpoint to be fed into hybrid switching recommender
        """

        if approach == "collab":
            if distance_metric == "corr":
                return CollaborativeRecommender(self._item_matrix, self._ratings)._corr(item_name)
            elif distance_metric == "cos":
                return CollaborativeRecommender(self._item_matrix, self._ratings)._cosine(item_name)
            else: raise ValueError("The distance heuristic must be 'corr', for correlation, or 'cos', for cosine similarity.")
            
        elif approach == "content":
            if distance_metric == "corr":
                return ContentRecommender(self._latent_cont_matrix, self._cont_ratings)._corr(item_name)
            elif distance_metric == "cos":
                return ContentRecommender(self._latent_cont_matrix, self._cont_ratings)._cosine(item_name)
            else: raise ValueError("The distance heuristic must be 'corr', for correlation, or 'cos', for cosine similarity.")

        elif approach == "weighted":
            if distance_metric == "corr":
                return WeightedRecommender(self._item_matrix, self._ratings, self._latent_cont_matrix, self._cont_ratings)._corr(item_name)
            elif distance_metric == "cos":
                return WeightedRecommender(self._item_matrix, self._ratings, self._latent_cont_matrix, self._cont_ratings)._cosine(item_name)
            else: raise ValueError("The distance heuristic must be 'corr', for correlation, or 'cos', for cosine similarity.")

        elif approach == "switch":
            if distance_metric == "corr":
                return SwitchRecommender(self._item_matrix, self._ratings, self._latent_cont_matrix, self._cont_ratings)._corr(item_name)
            elif distance_metric == "cos":
                return SwitchRecommender(self._item_matrix, self._ratings, self._latent_cont_matrix, self._cont_ratings)._cosine(item_name)
            else: raise ValueError("The distance heuristic must be 'corr', for correlation, or 'cos', for cosine similarity.")
           
        else: raise ValueError("Recommendation algorithm must be 'collab' for collaborative, 'content' for content, 'weighted' for weighted, or 'switch' for switch.")

    def prune_recommended(self, similarity_vector: DataFrame, top_n: int = 10,  minimum_ratings: int = 0) -> DataFrame:
        """
        takes an ordered list of recommendation, optionally removes any movies having fewer than a minimum number of ratings, and returns only the top n
        :param similarity_vector: list of recommendations
        :param top_n: number of movies to return
        :param minimum_ratings: minimum number of ratings needed to be returned
        """
        
        new_similarity_vector = similarity_vector[similarity_vector['Ratings_count'] > minimum_ratings]
        return new_similarity_vector.head(top_n)

    @lru_cache(maxsize = 1000)
    def MAP_at_k(self, k: int = 10, minratings: int = 0, maxratings: int = 610, dist_metr: str = "cos", approach: str = "collab"): 
        """writes AP@k scores to csv over all user-reclist pairs, and returns MAP@k metric* 
        :param k: recommendation list length
        :param minratings: minimum number of ratings to be included
        :param maxratings: maximum number of ratings to be included        
        :param dist_metric: method by which similarity is calculated
        :param approach: type of recommender used 
        """
        #TO DO: either remove or explicitly use minratings/maxratings
        #TO DO: separate printing function
        
        APdatapoints = []
        userAPs = []
        usercount: int = 0
        for _, current_user in self._held_out_matrix.iterrows():
            userhas: bool = False
            APs = []
            print("Current User: %s" % current_user)
            for itTitle, val in current_user.iteritems():
                if val == 1 and self._ratings['Number_of_ratings'][itTitle] in range(minratings, maxratings+1):
                    userhas = True
                    print("Seed for recommendation: %s" % itTitle)
                    recommendations = self.recommend_items(itTitle, dist_metr, approach)
                    pruned_recommendations = self.prune_recommended(recommendations, k, 0)
                    APs.append(self.average_precision(pruned_recommendations, current_user))
                    APdatapoints.append([self.average_precision(pruned_recommendations, current_user), self._ratings['Number_of_ratings'][itTitle]])
                    print("Precision: %s" % self.average_precision(self.prune_recommended(recommendations, 10, 0), current_user))
            userAPs.append(sum(APs)/k)
            if userhas:
                usercount = usercount + 1
        with open('scatterpointsweighted.csv','w') as file:
            for x in APdatapoints:
                file.write(str(x[1]))
                file.write(" ")
                file.write(str(x[0]))
                file.write('\n')
        if usercount > 0:
            MAP = sum(userAPs)/usercount
            return [MAP, usercount]
        else: return "None"
                
    def average_precision(self, recs: DataFrame, user_Data: DataFrame) -> float:
        """returns average precision for the recommendation list stemming from a seed item that was liked by user
        :param recs: dataframe of recommendations
        :param user_Data: the Series of user ratings for the pertinent movie
        """

        user = user_Data
        precisions = []
        for i in range(1, len(recs)+1):
            top_i_recs: List[strs] = recs["Title"].values[:i]
            precision: float = sum(user[itId] for itId in top_i_recs)/i
            precisions.append(precision)
        a_prec = sum(precisions)/len(recs)
        return a_prec

class CollaborativeRecommender(Recommender):
    """defines recommender that calculates similarity to an item based on which other item has the most similar set of user ratings"""

    def __init__(self, users_items: DataFrame, ratings: DataFrame):
        """
        :param users_items: matrix of user ratings of items
        :param ratings: matrix with mean ratings and ratings count
        """
        
        self._item_matrix: DataFrame = users_items
        self._ratings: DataFrame = ratings
            
    def _corr(self, item_name: str) -> pd.Series:
        """returns an item's correlation with all other items 
        :param item_name: name of item
        """

        #vector of ratings for given item
        item_ratings = self._item_matrix[item_name]
        
        if (item_ratings == 2.5).all(): #in case the entire vector is NaN
            
            similarity_vector = DataFrame({'Title': self._item_matrix.columns, 'Ratings_count': self._ratings['Number_of_ratings']})
            similarity_vector['Similarity'] = pd.Series([0 for x in range(len(similarity_vector.index))], index = similarity_vector.index)
            
        else:
            
            #matrix of correlations between given item and other items, minus missing values
            similarity_vector = DataFrame({'Title': self._item_matrix.columns, 'Similarity': self._item_matrix.corrwith(item_ratings), 'Ratings_count': self._ratings['Number_of_ratings']})
            similarity_vector = similarity_vector.sort_values(by = ["Similarity", "Ratings_count"], ascending = False)
            similarity_vector = similarity_vector[1:]
        
        return similarity_vector

    def _cosine(self, item_name: str) -> pd.Series:
        """returns an item's cosine-similarity with all other items
        :param item_name: name of item
        """

        item_ratings = self._item_matrix[item_name]
        if (item_ratings == 2.5).all():
            similarity_vector = DataFrame({'Title': self._item_matrix.columns, 'Ratings_count': self._ratings['Number_of_ratings']})
            similarity_vector['Similarity'] = pd.Series([0 for x in range(len(similarity_vector.index))], index = similarity_vector.index)
        else:    
            #matrix of cosine similarities between given item and other items
            similarity_list = []
            for col in self._item_matrix.columns:
                similarity_list.append(1 - distance.cosine(item_ratings, self._item_matrix.loc[:, col]))
            similarity_vector = DataFrame({'Title': self._item_matrix.columns, 'Similarity': similarity_list, 'Ratings_count': self._ratings['Number_of_ratings']})
            similarity_vector = similarity_vector.sort_values(by = ["Similarity", "Ratings_count"], ascending = False)
            similarity_vector = similarity_vector[1:]

        return similarity_vector

class ContentRecommender(Recommender):
    """defines recommender that calculates similarity to an item based on metadata"""

    #too many arguments -- fix structure?
    def __init__(self, latent_matrix: DataFrame, ratings: DataFrame, title: str = "title", metadata: str = "metadata"):
        """
        :param df3: dataframe
        """
        self._item_matrix: DataFrame = latent_matrix
        self._ratings: DataFrame = ratings
        self._metadata: str = metadata
        self._title: str = title

    def _corr(self, item_name: str) -> pd.Series:
        """returns an item's correlation with all other items
        :param item_name: name of item
        """

        #vector of ratings for given item
        item_values = self._item_matrix[item_name]
        
        #matrix of correlations between given item and other items, minus missing values
        similarity_vector = DataFrame({'Title': self._item_matrix.columns, 'Similarity': self._item_matrix.corrwith(item_values), 'Ratings_count': self._ratings})
        similarity_vector = similarity_vector.sort_values(by = ["Similarity", "Ratings_count"], ascending = False)
        similarity_vector = similarity_vector[1:]
        
        return similarity_vector

    def _cosine(self, item_name: str) -> pd.Series:
        """returns an item's cosine-similarity with all other items
        :param item_name: name of item
        """

        #vector of ratings for given item
        item_values = self._item_matrix[item_name]
        
        #matrix of cosine similarities between given item and other items
        similarity_list = []
        for col in self._item_matrix.columns:
            similarity_list.append(1 - distance.cosine(item_values, self._item_matrix[col]))
        similarity_vector = DataFrame({'Title': self._item_matrix.columns, 'Similarity': similarity_list, 'Ratings_count': self._ratings})
        similarity_vector = similarity_vector.sort_values(by = ["Similarity", "Ratings_count"], ascending = False)
        similarity_vector = similarity_vector[1:]
        
        return similarity_vector

class WeightedRecommender(Recommender):
    """defines recommender that calculates similarity based on a weighted average of content and collaborative recommendation"""

    def __init__(self, users_items: DataFrame, ratings: DataFrame, latent_cont_matrix: DataFrame, cont_ratings: DataFrame, alpha: float = 0.375):
        """
        :params: params of CollaborativeRecommender and ContentRecommender
        :param alpha: the averaging weight, i.e. how much relative emphasis is put on collaborative recommender
        """

        self._users_items: DataFrame = users_items
        self._ratings: DataFrame = ratings

        self._latent_cont_matrix: DataFrame = latent_cont_matrix
        self._cont_ratings: DataFrame = cont_ratings

        self._alpha = alpha

    def _corr(self, item_name: str) -> pd.Series:
        """returns an item's weighted average correlation with all other items
        :param item_name: name of item
        """
        #boot up collab/content rec lists
        collabrec: DataFrame = CollaborativeRecommender(self._users_items, self._ratings)._corr(item_name).sort_values(by = "Title", ascending = False)
        contrec: DataFrame = ContentRecommender(self._latent_cont_matrix, self._cont_ratings)._corr(item_name).sort_values(by = "Title", ascending = False)

        #then average
        similarity_vector = DataFrame({'Title': collabrec["Title"], 'Similarity': alpha*collabrec["Similarity"] + (1 - alpha)*contrec["Similarity"], 'Ratings_count': self._ratings})
        similarity_vector = similarity_vector.sort_values(by = ["Similarity", "Ratings_count"], ascending = False)
        return similarity_vector
    
    def _cosine(self, item_name: str) -> pd.Series:
        """returns an item's weighted average cosine-similarity with all other items
        :param item_name: name of item
        """
        #boot up collab/content rec lists
        collabrec: DataFrame = CollaborativeRecommender(self._users_items, self._ratings)._cosine(item_name).sort_values(by = "Title", ascending = False)
        contrec: DataFrame = ContentRecommender(self._latent_cont_matrix, self._cont_ratings)._cosine(item_name).sort_values(by = "Title", ascending = False)
        contrec.index = contrec["Title"] #fix patch

        #then average
        similarity_vector = DataFrame({'Title': collabrec["Title"], 'Similarity': self._alpha*collabrec["Similarity"] + (1 - self._alpha)*contrec["Similarity"], 'Ratings_count': collabrec["Ratings_count"]})
        similarity_vector = similarity_vector.sort_values(by = ["Similarity", "Ratings_count"], ascending = False)   
        return similarity_vector

class SwitchRecommender(Recommender):
   """defines architecture that switches from content to collaborative recommendation after seed has enough ratings"""
    
    def __init__(self, users_items: DataFrame, ratings: DataFrame, latent_cont_matrix: DataFrame, cont_ratings: DataFrame, cutoff: int = 100):
        """
        :params: params of CollaborativeRecommender and ContentRecommender
        :param cutoff: number of ratings for seed movie needed to switch from default content to collaborative method
        """

        self._users_items: DataFrame = users_items
        self._ratings: DataFrame = ratings

        self._latent_cont_matrix: DataFrame = latent_cont_matrix
        self._cont_ratings: DataFrame = cont_ratings

        self._cutoff = cutoff

    def _corr(self, item_name: str) -> pd.Series:
        """returns an item's correlation with all other items under switching regime
        :param item_name: name of item
        """

        #if you're past the cutoff, return the collaborative list
        if self._ratings["Number_of_ratings"][item_name] > self._cutoff:
            collabrec: DataFrame = CollaborativeRecommender(self._users_items, self._ratings)._corr(item_name).sort_values(by = "Similarity", ascending = False)
            similarity_vector = DataFrame({'Title': collabrec["Title"], 'Similarity': collabrec["Similarity"], 'Ratings_count': collabrec["Ratings_count"]})
            similarity_vector = similarity_vector.sort_values(by = ["Similarity", "Title"], ascending = False)
            return similarity_vector

        #else, content list
        else:
            contrec: DataFrame = ContentRecommender(self._users_items, self._ratings)._corr(item_name).sort_values(by = "Similarity", ascending = False)
            contrec.index = contrec["Title"] #fix patch
            similarity_vector = DataFrame({'Title': contrec["Title"], 'Similarity': contrec["Similarity"], 'Ratings_count': contrec["Ratings_count"]})
            similarity_vector = similarity_vector.sort_values(by = ["Similarity", "Ratings_count"], ascending = False)
            return similarity_vector
    
    def _cosine(self, item_name: str) -> pd.Series:
        """returns an item's cosine-similarity with all other items under switching regime
        :param item_name: name of item
        """

        #if you're past the cutoff, return the collaborative list
        if self._ratings["Number_of_ratings"][item_name] > self._cutoff:
            collabrec: DataFrame = CollaborativeRecommender(self._users_items, self._ratings)._cosine(item_name)
            similarity_vector = DataFrame({'Title': collabrec["Title"], 'Similarity': collabrec["Similarity"], 'Ratings_count': collabrec["Ratings_count"]})
            similarity_vector = similarity_vector.sort_values(by = ["Similarity", "Title"], ascending = False)
            return similarity_vector

        #else, content list
        else:
            contrec: DataFrame = ContentRecommender(self._latent_cont_matrix, self._cont_ratings)._cosine(item_name)
            contrec.index = contrec["Title"] #fix patch
            similarity_vector = DataFrame({'Title': contrec["Title"], 'Similarity': contrec["Similarity"], 'Ratings_count': contrec["Ratings_count"]})
            similarity_vector = similarity_vector.sort_values(by = ["Similarity", "Ratings_count"], ascending = False)
            return similarity_vector
        
def load_movie_data(ratings_data: str = "ratings.csv", movies_data: str = "movies.csv", tags_data: str = "tags.csv"):
    """loads and combines movie-related datasets (ratings, titles, tags) from the recommender folder, feeds them into RatingsData object        
    :param ratings_data: .csv file of movie ratings
    :param movies_data: .csv file of movie titles
    :param tags_data: csv file of movie tags
    """

    #load different movie datasets
    ratings: DataFrame = pd.read_csv(ratings_data)
    ratings.drop(['timestamp'], 1, inplace = True)
    
    titles: DataFrame = pd.read_csv(movies_data)

    ratings_with_titles: DataFrame = pd.merge(ratings, titles, on = "movieId")

    tags: DataFrame = pd.read_csv(tags_data)
    tags.drop(['timestamp'], 1, inplace = True)

    #join datasets into one: dump genres and tags into metadata, clean dataset
    full_movie_dataset: DataFrame = pd.merge(ratings_with_titles, tags, on = ["userId", "movieId"], how = "left")
    full_movie_dataset.fillna("", inplace = True)
    full_movie_dataset = full_movie_dataset.groupby('movieId')['tag'].apply(lambda x: "%s" % ' '.join(x))
    full_movie_dataset = pd.merge(ratings_with_titles, full_movie_dataset, on = "movieId", how = "left")
    full_movie_dataset['metadata'] = full_movie_dataset[["tag", "genres"]].apply(lambda x: ' '.join(x), axis = 1)
    full_movie_dataset.drop(["tag", "genres"], 1, inplace = True)
    full_movie_dataset.to_csv(r'/Users/jzymet/Desktop/recommender/full_movie_dataset.csv', index = False)

    return full_movie_dataset
