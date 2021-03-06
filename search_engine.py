import pickle
import re
from math import log

import h5py
import nltk
from nltk.tokenize import word_tokenize
from scipy.spatial.distance import cdist
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import TfidfVectorizer

from pageRank import TSPageRank
from preprocessor import Preprocessor

nltk.download('punkt')


class SearchEngine:
    model = SentenceTransformer('bert-base-nli-mean-tokens')
    vectorizer = TfidfVectorizer()
    document_lengths = {}
    documents = []
    document_titles = {}
    urls = []
    tf = {}
    idf = {}
    url_to_doc = {}
    document_embeddings = None
    document_embeddings_field2 = None
    embeddings_file = f"data/bert_embeddings.h5"
    preprocessor = Preprocessor(stemmer_flag=True, stopwords_flag=True, min_word_length=2)

    pagerank = TSPageRank(num_iterations=4)

    def clean_text(self, text: str):
        text = re.sub(r"[^a-zA-Z0-9 ]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def __init__(self, fresh_start=False):
        self.import_data(fresh_start)
        self.create_model(fresh_start)

    def import_data(self, fresh_start):
        data = pickle.load(open('data/data.pickle', 'rb'))
        for url, text_dict in data.items():
            self.urls.append(url)
            document1 = text_dict['atext']
            document2 = text_dict['body']
            doc = "{} {}".format(document1, document2)
            doc = self.clean_text(doc)
            self.documents.append(document1)
            self.url_to_doc[url] = document1
            self.document_titles[url] = text_dict['title']
            if fresh_start:
                self.add_to_index(doc, url)
        if fresh_start:
            self.add_idf(N=len(data))
            with open('data/tfidf_data.pickle', 'wb') as fptr:
                pickle.dump([self.tf, self.idf, self.document_lengths], fptr)
        else:
            with open('data/tfidf_data.pickle', 'rb') as fptr:
                self.tf, self.idf, self.document_lengths = pickle.load(fptr)

    def create_model(self, fresh_start):
        if fresh_start:
            self.create_embeddings()
        else:
            self.read_embeddings()

    def search(self, query, metric='cosine'):
        qresults = []
        query = self.clean_text(query)
        qwords = word_tokenize(query.lower())
        results = self.get_cosine(qwords)
        query = self.clean_text(query.lower())
        qembedding = self.model.encode(query)
        qdistances = cdist([qembedding], self.document_embeddings, metric)[0]
        bertresults = list(zip(self.urls, qdistances))
        bertresults = sorted(bertresults, key=lambda x: x[1])
        semantically_similar_docs = []
        if len(results) > 10:
            results = results[:10]
        results += bertresults
        temp = []
        urls = []
        for i in range(100):
            if len(temp) > 20:
                break
            if results[i][0] not in urls:
                urls.append(results[i][0])
                temp.append(results[i])
            if bertresults[i][0] not in urls:
                urls.append(bertresults[i][0])
                temp.append(bertresults[i])
        results = temp
        for url, score in results:
            doc = self.url_to_doc[url]
            doc = self.clean_text(doc.lower())
            doc_embeddings = self.model.encode(doc)
            distances = cdist([doc_embeddings], self.document_embeddings, "cosine")[0]
            doc_results = list(zip(self.urls, distances))
            doc_results = sorted(doc_results, key=lambda x: x[1])
            for item in doc_results[:5]:
                if item not in semantically_similar_docs:
                    semantically_similar_docs.append(item)
        results += self.get_pagerank(semantically_similar_docs)
        for url, score in results:
            title = self.document_titles[url]
            qresults.append((title, url))
        return qresults

    def get_cosine(self, query_tokens):
        query_length = 0
        scores = {}
        for token in set(query_tokens):
            if token not in self.tf:
                continue
            qtoken_tf = query_tokens.count(token)
            idf = self.idf[token]
            qtoken_tfidf = qtoken_tf * idf
            query_length += qtoken_tfidf ** 2
            for doc_id, dtoken_tfidf in self.tf[token].items():
                if doc_id not in scores:
                    scores[doc_id] = 0
                scores[doc_id] += qtoken_tfidf * dtoken_tfidf
        scores = self.normalize_score(scores, query_length)
        scores = sorted(scores, key=lambda x: x[1], reverse=True)
        return scores

    def normalize_score(self, scores, query_length):
        normalized_scores = []
        for doc_id, score in scores.items():
            doc_length = self.document_lengths[doc_id]
            score = score / ((query_length * doc_length) ** (1 / 2))
            normalized_scores.append((doc_id, score))
        return normalized_scores

    def clean_text(self, text):
        text = text.lower()
        text = re.sub(r'[^a-zA-Z0-9 ]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def read_embeddings(self):
        h5f1 = h5py.File(self.embeddings_file, 'r')
        self.document_embeddings = h5f1['dataset_1'][:]
        h5f1.close()

    def create_embeddings(self):
        self.document_embeddings = self.model.encode(self.documents)
        h5f1 = h5py.File(self.embeddings_file, 'w')
        h5f1.create_dataset('dataset_1', data=self.document_embeddings)
        h5f1.close()

    def add_to_index(self, text, url):
        words = word_tokenize(text)
        for w in words:
            if w not in self.tf:
                self.tf[w] = {}
            if url not in self.tf[w]:
                self.tf[w][url] = 0
            self.tf[w][url] += 1

    def add_idf(self, N):
        for w, doc in self.tf.items():
            idf = log(N / len(doc))
            self.idf[w] = idf
            for url, tf in doc.items():
                tfidf = tf * idf
                self.tf[w][url] = tfidf
                if url not in self.document_lengths:
                    self.document_lengths[url] = 0
                self.document_lengths[url] += tfidf ** 2

    def get_pagerank(self, results):
        results = sorted(results, key=lambda x: x[1])
        s = sum([x[1] for x in results])
        base = max([x[1] for x in results])
        results = {x[0]: (x[1] + base) / s for x in results}
        pgscores = self.pagerank.get_pageranks(results)
        return pgscores


def main():
    se = SearchEngine(fresh_start=False, method='TFIDF')
    results = se.search("Cornelia Caragea")
    print([print(r) for r in results])


if __name__ == '__main__':
    main()
