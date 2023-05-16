from flask import Flask, render_template, request, redirect, url_for
from flask_pymongo import PyMongo
import json
import pymongo
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
import json
import zipfile
from io import BytesIO
import gc 
from flask import jsonify
from bson import ObjectId
from bson.json_util import dumps
from collections import Counter
import plotly.graph_objs as go
from plotly.utils import PlotlyJSONEncoder
import pandas as pd
import re
from collections import defaultdict
from plotly.graph_objs import Bar, Table, Histogram, Pie
import plotly.colors
from zipfile import ZipFile
import os
import shutil
from werkzeug.utils import secure_filename
import tarfile
from flask import current_app


# Define the uploads folder
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")

# Create the uploads folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Store the sensitive information in variables
# connection_url = "mongodb://localhost:27017"  # remove this
database_name = "db"  # use your actual database name

# Configure Flask app
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["ALLOWED_EXTENSIONS"] = {"zip", "tar", "txt", "csv", "json"}

# Configure PyMongo to use the MongoDB URL
app.config["MONGO_URI"] = os.getenv('MONGO_URI', "mongodb+srv://admin:admin@samplecluster.cyfvrvo.mongodb.net/db?retryWrites=true&w=majority")

mongo = PyMongo(app)




ITEMS_PER_PAGE = 25

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * ITEMS_PER_PAGE
    data_cursor = mongo.db.json_data.find().skip(offset).limit(ITEMS_PER_PAGE)
    data = list(data_cursor)
    total_items = mongo.db.json_data.count_documents({})
    return render_template('index.html', data=data, page=page, total_items=total_items, ITEMS_PER_PAGE=ITEMS_PER_PAGE)


def get_label_counts(data_cursor):
    return Counter([item['label'] for item in data_cursor])


def get_stats(data):
    label_text_counts = defaultdict(int)
    unique_texts = set()
    unique_labels = set()
    unicode_pattern = re.compile(r'[^\x00-\x7F]+')
    num_unicode_rows = 0

    for item in data:
        label_text_counts[(item['label'], item['text'])] += 1
        unique_texts.add(item['text'])
        unique_labels.add(item['label'])
        if unicode_pattern.search(item['text']):
            num_unicode_rows += 1

    num_duplicates = sum([count - 1 for count in label_text_counts.values() if count > 1])
    num_texts = len(unique_texts)
    num_labels = len(unique_labels)
    total_rows = len(data)

    return num_duplicates, num_texts, num_labels, total_rows, num_unicode_rows



@app.route('/combined')
def combined():
    # Retrieve data from MongoDB
    data_cursor = mongo.db.json_data.find({}, {'label': 1, 'text': 1, '_id': 0})
    data = [item for item in data_cursor]

    # Calculate statistics
    label_counts = get_label_counts(data)
    num_duplicates, num_texts, num_labels, total_rows, num_unicode_rows = get_stats(data)
    avg_texts_per_label = num_texts // num_labels

    sorted_labels = sorted(label_counts.items(), key=lambda x: x[1])

    minority_classes = [label for label, count in sorted_labels if count == sorted_labels[0][1]]
    majority_classes = [label for label, count in sorted_labels if count == sorted_labels[-1][1]]

    minority_count = sum(label_counts[label] for label in minority_classes)
    majority_count = sum(label_counts[label] for label in majority_classes)

    # Create a bar chart using Plotly
    trace = go.Bar(y=list(label_counts.keys()), x=list(label_counts.values()), orientation='h', marker=dict(color='rgb(57, 143, 249)'))
    layout = go.Layout(title='Bar Chart of Text Field by Unique Count of Label Field ', xaxis=dict(title='Unique Count of Label Field'), yaxis=dict(title='Text Field'))
    figure_bar = go.Figure(data=[trace], layout=layout)

   # Calculate percentage for each label
    total_count = sum(label_counts.values())
    percentage = [(count / total_count) * 1000 for count in label_counts.values()]

    # Create a frequency table using Plotly
    freq_trace = go.Table(
        header=dict(values=['Label', 'Count', 'Percentage'], fill_color='grey', align='left'),
        cells=dict(values=[list(label_counts.keys()), list(label_counts.values()), percentage], fill_color='lightgrey', align='left'))
    figure_freq = go.Figure(data=[freq_trace])
    figure_freq.update_layout(height=600)

    # Create a pie chart using Plotly
    pie_trace = go.Pie(labels=list(label_counts.keys()), values=list(label_counts.values()), marker=dict(colors=plotly.colors.sequential.RdBu), hoverinfo='label+value', textinfo='none')
    pie_layout = go.Layout(title='Pie Chart of Label Frequencies ')
    figure_pie = go.Figure(data=[pie_trace], layout=pie_layout)

    # Create the bar chart data
    bar_data = go.Bar(x=['Minority Classes', 'Majority Classes'], y=[minority_count, majority_count], marker=dict(color='rgb(57, 143, 249)'))
    # Create the layout for the bar chart
    bar_layout = go.Layout(title='Total Count of Minority and Majority Classes ', xaxis=dict(title='Class Type'), yaxis=dict(title='Count'))

    # Create the bar chart
    figure_min_max_bar = go.Figure(data=[bar_data], layout=bar_layout)
    figure_min_max_bar.update_layout(height=1235)

    # Delete objects no longer needed
    del trace, layout, label_counts, data ,pie_trace, pie_layout

    # Force garbage collection
    gc.collect()

    # Encode the bar chart as JSON
    figure_bar_json = json.dumps(figure_bar, cls=PlotlyJSONEncoder)
    figure_freq_json = json.dumps(figure_freq, cls=PlotlyJSONEncoder)
    figure_pie_json = json.dumps(figure_pie, cls=PlotlyJSONEncoder)
    figure_min_max_bar_json = json.dumps(figure_min_max_bar, cls=PlotlyJSONEncoder)

    return render_template('combined.html', bar_chart=figure_bar_json, freq_table=figure_freq_json, pie_chart=figure_pie_json, min_max_bar_chart=figure_min_max_bar_json, num_duplicates=num_duplicates, num_texts=num_texts, num_labels=num_labels, total_rows=total_rows, num_unicode_rows=num_unicode_rows, avg_texts_per_label=avg_texts_per_label)





@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['json_file']
    if file:
        file_content = BytesIO(file.read())
        if zipfile.is_zipfile(file_content):
            records_to_insert = []
            with zipfile.ZipFile(file_content) as zfile:
                for name in zfile.namelist():
                    with zfile.open(name) as json_file:
                        try:
                            data = json.load(json_file)
                            if isinstance(data, dict):
                                records_to_insert.append(data)
                            elif isinstance(data, list):
                                for item in data:
                                    if isinstance(item, dict):
                                        records_to_insert.append(item)
                                    else:
                                        return "Invalid JSON format", 400
                            else:
                                return "Invalid JSON format", 400
                        except json.JSONDecodeError:
                            return "Error decoding JSON file", 400

            if records_to_insert:
                mongo.db.json_data.insert_many(records_to_insert)
                return redirect(url_for('combined'))
            else:
                return "No records to insert", 400
        else:
            return "Uploaded file is not a zip file", 400
    else:
        return "No file uploaded", 400
    




def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]

@app.route("/upload_file", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        if "file" not in request.files:
            return redirect(request.url)
        file = request.files["file"]
        if file.filename == "":
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            extract_and_store_zip(filename)
            return redirect(url_for("upload_file", filename=filename))
    return render_template("upload_file.html")

def extract_and_store_file(filename):
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file_ext = os.path.splitext(filename)[1]

    if file_ext == ".zip":
        with ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(app.config["UPLOAD_FOLDER"])
    elif file_ext == ".tar":
        with tarfile.open(file_path, "r") as tar_ref:
            tar_ref.extractall(app.config["UPLOAD_FOLDER"])
    else:
        shutil.copy(file_path, os.path.join(app.config["UPLOAD_FOLDER"], "folder"))

    if "model" not in mongo.db.list_collection_names():
        mongo.db.create_collection("model")

    model_collection = mongo.db["model"]

    for root, dirs, files in os.walk(os.path.join(app.config["UPLOAD_FOLDER"], "folder")):
        for file in files:
            with open(os.path.join(root, file), "r") as f:
                data = f.read()
                model_collection.insert_one({"filename": file, "data": data})

    os.remove(file_path)


    
    


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)