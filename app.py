import json 
from flask import Flask, jsonify, request
import requests
import base64
import os
from bs4 import BeautifulSoup
import openai
from openai import OpenAI
from DatabaseConnection import DatabaseConnection
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
client = OpenAI(
    # This is the default and can be omitted
    api_key=os.getenv('OPENAI_API_KEY')
)


#openai.api_key = os.getenv('OPENAI_API_KEY')
news_titles = []
api_config = {
    'img_dir' : '/home/tuvex/SyncNewsApi/api/img/'
}
news_sync_config = {
    'wordpress_user' : os.getenv('NEWS_SYNC_WP_USER'),
    'wordpress_password' : os.getenv('NEWS_SYNC_WP_PASSWD'),
    'source_api_url' : 'https://www.cordoba.gov.co/publicaciones/noticias/?tema=5',
    'news_api_url' : 'https://periodicotierracaliente.co/',
    'default_author' : 5
}

headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36'}
db = DatabaseConnection()

def getPublishedNews():
    connection = db.connection
    cursor = connection.cursor()
    try:        
        select_query = "SELECT * FROM news_titles WHERE fecha_registro >= CURRENT_TIMESTAMP - INTERVAL '30 days'"
        cursor.execute(select_query)
        news_data = cursor.fetchall()
        for n in news_data:
            fecha_formateada = n[3].strftime('%Y-%m-%d') if isinstance(n[3], datetime) else n[3]
            news_titles.append({
                'title' : n[1],
                'type' : n[2],
                'fecha' : fecha_formateada
            })
    except (Exception, psycopg2.Error) as error:
        print(f"Error al conectar con PostgreSQL: {error}")
    finally:
        cursor.close() 

def saveNewsTitle(title, newsType):    
    connection = db.connection
    cursor = connection.cursor()  
    try:        
        insert_query = '''
        INSERT INTO news_titles (title, type)
        VALUES (%s, %s);
        '''
        data = (title, newsType)
        cursor.execute(insert_query, data)
        connection.commit()
    except (Exception, psycopg2.Error) as error:
        print(f"Error al conectar con PostgreSQL: {error}")
    finally:
        cursor.close() 
        #connection.close()

def chat_with_gpt(prompt):
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        model="gpt-3.5-turbo",
    )
    return chat_completion.choices[0].message.content

def getWordpressToken(wordpress_user, wordpress_password):    
    wordpress_credentials = wordpress_user + ':' + wordpress_password
    wordpress_token = base64.b64encode(wordpress_credentials.encode())
    return wordpress_token.decode('utf-8')

def getWordpressHeader(wordpress_user, wordpress_password):    
    wordpress_credentials = wordpress_user + ':' + wordpress_password
    wordpress_token = base64.b64encode(wordpress_credentials.encode())
    news_sync_config['token'] = wordpress_token.decode('utf-8')
    wordpress_header = {'Authorization': 'Basic ' + news_sync_config['token']}
    return wordpress_header

def getImage(imageURL):
    imageData = requests.get(imageURL, headers=headers)
    imageName = imageURL[imageURL.rindex('/')+1:]
    with open(api_config['img_dir']+imageName, 'wb') as handler:
        handler.write(imageData.content)
    return api_config['img_dir']+imageName

def processPostData(post):
    post_helper = post
    new_content = chat_with_gpt("En el contexto de un periodista independiente reescribe nuevamente el siguiente texto: "+post['content'])
    post_helper['content'] = new_content
    return post_helper

def getPostDataFromUrl(type, url):
    post = {}
    try:
        match type:
            case 'gobcordoba':
                baseURL = 'https://www.cordoba.gov.co'
                page = requests.get(url, headers=headers)
                soup = BeautifulSoup(page.content, "html.parser")
                titleElement = soup.select('#infoPrincipal h1')
                title = titleElement[0].text
                featuredImageElement = soup.select('#infoPrincipal .modContent img')
                featuredImageURL = baseURL+featuredImageElement[0]['src']
                featuredImageAbsPath = getImage(featuredImageURL)
                contentElement = soup.select('#infoPrincipal .modContent .pgel')
                content = contentElement[0].text
                post = {
                    'title': title,
                    'featuredImageURL': featuredImageURL,
                    'featuredImageAbsPath': featuredImageAbsPath,
                    'content': content 
                }    
                processPostData(post)
    except openai.BadRequestError as e:
        print(f"Error en la solicitud: {e}")
    except openai.AuthenticationError as e:
        print(f"Error de autenticación: {e}")
    except openai.PermissionDeniedError as e:
        print(f"Permiso denegado: {e}")
    except openai.NotFoundError as e:
        print(f"No se pudo encontrar el recurso: {e}")
    except openai.UnprocessableEntityError as e:
        print(f"No se pudo procesar la entidad: {e}")
    except openai.RateLimitError as e:
        print(f"Se ha superado el límite de tasa: {e}")
    except openai.APIConnectionError as e:
        print(f"Error de conexión a la API: {e}")
    except openai.InternalServerError as e:
        print(f"Error en el servidor de OpenAI: {e}")
    except openai.Timeout as e:
        print(f"La solicitud tardó demasiado tiempo en responder: {e}")
    except Exception as e:
         print(f"Ocurrió un error inesperado: {e}")

    return post



def getNewsDataFromSource(newsType, url):
    posts = []
    match newsType:
        case 'gobcordoba':
            page = requests.get(url, headers=headers)
            soup = BeautifulSoup(page.content, "html.parser")
            news_gobcord = [n['title'] for n in news_titles if n['type'] == 'gobcordoba']
            for e in soup.select('div.contentPubTema div.post-content h2.title a'):
                title = e.text.strip()
                url_post = e['href']                
                if title in news_gobcord:
                    posts.append(getPostDataFromUrl(newsType, url_post))
                    news_titles.append({
                        'title' : title,
                        'type' : 'gobcordoba'
                    })
                    news_gobcord.append(title)
                    saveNewsTitle(title, newsType)
                    
    return posts
                    
def getWordpressImageID(imageAbsPath):
    imageFileData = open(imageAbsPath, 'rb').read()   
    imageName = imageAbsPath[imageAbsPath.rindex('/')+1:] 
    wordpress_image_headers = {'Authorization': 'Basic ' + news_sync_config['token']}
    wordpress_image_headers['Content-Type'] = 'image/jpg'
    wordpress_image_headers['Content-Disposition'] = 'attachment; filename='+imageName

    media = {
        'title' : imageName,
        'status': 'published',
        'slug' : imageName.lower().replace(' ', '-'),
    }

    responseImageWP = requests.post(news_sync_config['news_api_url']+'wp-json/wp/v2/media',headers=wordpress_image_headers, json=media, data=imageFileData)
    imageId = responseImageWP.json().get('id') if responseImageWP else ''
    return imageId

def publishPostToWordpress(postData):
    wordpress_header = getWordpressHeader(news_sync_config['wordpress_user'], news_sync_config['wordpress_password'])
    imageID = getWordpressImageID(postData['featuredImageAbsPath'])
    data = {
        'title' : postData['title'],
        'status': 'draft',
        'slug' : postData['title'].lower().replace(' ', '-'),
        'content': postData['content'],
        'featured_media' : imageID,
        'author' : news_sync_config['default_author']
    }
    responseWP = requests.post(news_sync_config['news_api_url']+'wp-json/wp/v2/posts',headers=wordpress_header, json=data)
    response = {}    
    os.remove(postData['featuredImageAbsPath']) 
    return response


@app.route('/sync-news', methods=['POST'])
def sync_news_post():
    response = {}   
    posts = getNewsDataFromSource('gobcordoba', news_sync_config['source_api_url'])
    for p in posts:
        publishPostToWordpress(p)
    return jsonify(response) 



@app.route('/sync-ventana', methods=['POST'])
def sync_data():
    error = True
    wordpress_user = os.getenv('NEWS_VENTANA_WP_USER')
    wordpress_password = os.getenv('NEWS_VENTANA_WP_PASSWD')
    wordpress_credentials = wordpress_user + ':' + wordpress_password
    wordpress_token = base64.b64encode(wordpress_credentials.encode())
    wordpress_header = {'Authorization': 'Basic ' + wordpress_token.decode('utf-8')}
    api_url = 'https://laventanadecordoba.com/'
    URL = "https://burbujapolitica.com/"
    page = requests.get(URL)
    soup = BeautifulSoup(page.content, "html.parser")
    element = soup.select('.slide-title a')
    latestURL = element[0]['href']
    latestPage = requests.get(latestURL)
    latestSoup = BeautifulSoup(latestPage.content, "html.parser")
    latestTitleElement = latestSoup.select('.entry-title')
    latestTitle = latestTitleElement[0].text
    latestContentElement = latestSoup.select('.entry-content')
    latestContent = latestContentElement[0].text
    latestImageElement = latestSoup.select('.aft-post-thumbnail-wrapper img')
    latestImage = latestImageElement[0]['data-src']
    latestImageName = latestImage[latestImage.rindex('/')+1:]

    latestImageData = requests.get(latestImage)
    with open('/home/tuvex/SyncNewsApi/api/img/'+latestImageName, 'wb') as handler:
        handler.write(latestImageData.content)
    
    latestImageFileData = open('/home/tuvex/SyncNewsApi/api/img/'+latestImageName, 'rb').read()
    
    wordpress_image_headers = {'Authorization': 'Basic ' + wordpress_token.decode('utf-8')}
    wordpress_image_headers['Content-Type'] = 'image/jpg'
    wordpress_image_headers['Content-Disposition'] = 'attachment; filename='+latestImageName


    media = {
        'title' : latestImageName,
        'status': 'published',
        'slug' : latestImageName.lower().replace(' ', '-'),
    }

    responseImageWP = requests.post(api_url+'wp-json/wp/v2/media',headers=wordpress_image_headers, json=media, data=latestImageFileData)
    latestImageId = responseImageWP.json().get('id') if responseImageWP else ''

    data = {
        'title' : latestTitle,
        'status': 'draft',
        'slug' : latestTitle.lower().replace(' ', '-'),
        'content': latestContent,
        'featured_media' : latestImageId
    }


    responseWP = requests.post(api_url+'wp-json/wp/v2/posts',headers=wordpress_header, json=data)
    error = not (latestTitle and latestContent and latestImage)
    response = {}

    if(error):
        response['error'] = 'No se pudo leer la información!'


    return jsonify(response) 

def init():
    getPublishedNews()
    

if __name__ == '__main__':
   init()
   app.run(port=7000)