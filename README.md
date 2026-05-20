<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![LinkedIn][linkedin-shield]][linkedin-url]
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://github.com/isislab-unisa/KGSum">
    <img src="images/logo.png" alt="Logo" width="100" height="80">
  </a>

<h3 align="center">KgSum</h3>

  <p align="center">
    A Python application for extracting, preparing, and classifying Knowledge Graphs, leveraging LLMs and traditional machine learning.<br>
    <b>Thesis Project, University of Salerno, ISISLab</b>
    <br />
    <a href="https://github.com/isislab-unisa/KGSum/wiki"><strong>Explore the docs »</strong></a>
    <br />
    <a href="https://github.com/isislab-unisa/KGSum/issues/new?labels=bug&template=bug-report---.md">Report Bug</a>
    &middot;
    <a href="https://github.com/isislab-unisa/KGSum/issues/new?labels=enhancement&template=feature-request---.md">Request Feature</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
        <li><a href="#configuration">Configuration</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#docker-deployment">Docker Deployment</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

<!-- ABOUT THE PROJECT -->
## About The Project

<a href="https://github.com/mariocosenza/kgsum">
  <img src="images/DemoKgSum.gif" alt="KgSum demo" width="100%">
</a>

**Demo video (direct link):** [DemoKgSum](images/DemoKgSum.mov)

**KgSum** is a Python application for extracting, preparing, and classifying Knowledge Graphs (KGs). It combines Large Language Models (such as Mistral Instructor 7B with QLoRA) and traditional machine learning for effective graph classification and profiling.

University of Salerno  
Lab: ISISLab  
Author: Mario Cosenza, Maria Angela Pellegrino, Gabriele Tuozzo 

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

* [Python 3.12](https://www.python.org/)
* [PyTorch](https://pytorch.org/)
* [Transformers](https://huggingface.co/docs/transformers)
* [spaCy](https://spacy.io/)
* [Flask](https://flask.palletsprojects.com/)
* [Next.js](https://nextjs.org/)
* [React](https://reactjs.org/)
* [TailwindCSS](https://tailwindcss.com/)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- GETTING STARTED -->
## Getting Started

Follow these steps to set up KgSum locally.

### Prerequisites

#### For Local Machine Learning Backend:
- **Miniconda** (required)
- **Python 3.12** (suggested)
- **CUDA 12.8** (for transformer models like Mistral)
- **NVIDIA GPU** (recommended: RTX 3070 or higher)

#### For Frontend:
- **Node.js** 
- **npm**

#### For Docker Deployment:
- **Docker**
- **Docker Compose**

### Installation

#### Local Setup (Machine Learning Backend)

1. Clone the repository:
   ```sh
   git clone https://github.com/mariocosenza/kgsum.git
   cd kgsum
   ```

2. Create and activate conda environment:
   ```sh
   conda env create -f environment.yml
   conda activate kgsum
   ```

3. **For GPU/Transformer Models (Mistral):**
   - Comment out CUDA libraries in `environment.yml`
   - Change TensorFlow version to GPU-compatible version as suggested in comments

#### Frontend Setup

1. Install dependencies:
   ```sh
   npm install
   ```

2. Run the frontend:
   ```sh
   npm run dev
   ```

3. **For GraphDB embedding visualization:**
   - Replace GraphDB's `security-config.xml` with the one in `/docker/graphdb`

### Configuration

#### Environment Variables

Set the following environment variables in your shell:

```sh
export GEMINI_API_KEY=your_gemini_api_key_here
export LOCAL_ENDPOINT_LOV=http://your-local-endpoint
export LOCAL_ENDPOINT=http://your-local-endpoint
export SECRET_KEY=your_secret_key_here
export UPLOAD_FOLDER=/path/to/uploads
export UPLOAD=true
export NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=your_clerk_publishable_key
export CLASSIFICATION_API_URL=http://localhost:5000
export GITHUB_TOKEN=your_github_token_here
```

#### Backend Configuration

Configure the backend by editing `config.json`:

```json
{
  "labeling" : {
    "use_gemini": false,
    "search_zenodo": true,
    "search_github": true,
    "search_lod_cloud": true,
    "stop_before_merging": false
  },
  "extraction": {
    "start_offset": 0,
    "step_numbers": 10,
    "step_range": 16,
    "extract_sparql": true,
    "query_lov": true
  },
  "processing" : {
    "use_ner": true,
    "use_filter": true
  },
  "training" : {
     "classifier": "NAIVE_BAYES",
     "feature": ["CURI", "PURI", "LAB", "CON", "TLDS", "VOC", "LCN", "LPN", "DSC", "SBJ"],
     "oversample": true,
     "max_token": 36000,
     "use_tfidf_autoencoder": true
  },
  "profile": {
    "store_profile_after_training": false,
    "base_domain": "http://www.isislab.it"
  },
  "general_settings": {
    "info": "Possible classifiers: SVM, NAIVE_BAYES, KNN, J48, MISTRAL, MLP, DEEP, BATCHNORM, Phase: LABELING, EXTRACTION, PROCESSING, TRAINING, STORE",
    "start_phase": "labeling",
    "stop_phase": "training",
    "allow_upload": true
  }
}
```

**Available Classifiers:** SVM, NAIVE_BAYES, KNN, J48, MISTRAL, MLP, DEEP, BATCHNORM  
**Available Features:** CURI, PURI  
**Processing Phases:** LABELING, EXTRACTION, PROCESSING, TRAINING, STORE

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- USAGE EXAMPLES -->
## Usage

### Training Process

#### Full Training Pipeline
Run the complete training process from extraction to model training:
```sh
python train.py
```

#### Individual Script Training
For more fine-tuned control, run individual scripts in `/src`:
```sh
# Run scripts in /src directory for specific phases
```

### Running the Application

#### Local Flask Server
After completing training, start the WSGI Flask server on port 5000:
```sh
python app.py
```

#### Prerequisites for Complete Profiling
- **Linked Open Vocabularies (LOV) instance** is required for complete profiling and initial data extraction

### API Usage

Send POST requests to:
- `/api/v1/profile/sparql`
- `/api/v1/profile/file`

Profiles are returned as JSON by default. To export the same generated profile as RDF, pass `format=rdf` for RDF/XML, `format=ttl` for Turtle, `format=nt` for N-Triples, or `format=jsonld` for JSON-LD. The API also honors matching `Accept` headers such as `application/rdf+xml` and `text/turtle`.

Refer to the Swagger documentation for detailed request and response formats.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- DOCKER DEPLOYMENT -->
## Docker Deployment

### Quick Setup with Pre-trained Model

For a simpler deployment using the pre-trained Naive Bayes model:

1. Navigate to the docker directory:
   ```sh
   cd /docker
   ```

2. Fill the `.env` file with your configuration

3. Run with Docker Compose:
   ```sh
   docker-compose up
   ```

### Individual Docker Services

Three individual Dockerfiles are provided for custom deployments:
- **Backend** service
- **Frontend** service  
- **GraphDB** configuration

### Hardware Requirements

#### Tested Configuration
| Component | Specification                    |
|-----------|----------------------------------|
| CPU       | AMD Ryzen 5800x                 |
| RAM       | 32 GB DDR4 3600MHz             |
| GPU       | NVIDIA RTX 3070                |

#### Recommended Configuration
| Component | Specification                    |
|-----------|----------------------------------|
| RAM       | 64+ GB (larger size suggested)  |
| GPU       | High-performance GPU for better LLM performance |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ROADMAP -->
## Roadmap

- [x] Add Swagger API documentation
- [x] Expand coverage for more LLMs
- [x] Improve Docker deployment documentation
- [ ] Add more dataset preparation examples
- [ ] Add performance optimization guides
- [x] Enhance frontend visualization features

See the [open issues](https://github.com/mariocosenza/kgsum/issues) for a full list of proposed features (and known issues).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Top contributors:

<a href="https://github.com/isislab-unisa/KGSum/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=isislab-unisa/KGSum" alt="contrib.rocks image" />
</a>

<!-- LICENSE -->
## License

Distributed under the MIT License. See `LICENSE.txt` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTACT -->
## Contact

Mario Cosenza - [@mario_cosenza_](https://x.com/mario_cosenza_) - cosenzamario@proton.me  
Maria Angela Pellegrino - mapellegrino@unisa.it
Gabriele Tuozzo - gtuozzo@unisa.it

Project Link: [https://github.com/isislab-unisa/KGSum](https://github.com/mariocosenza/kgsum)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

* University of Salerno, ISISLab
* [Mistral LLM](https://mistral.ai/)
* [LOD Cloud](https://lod-cloud.net/)
* [Zenodo](https://zenodo.org/)
* [Linked Open Vocabularies](https://lov.linkeddata.es/)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/isislab-unisa/KGSum.svg?style=for-the-badge
[contributors-url]: https://github.com/isislab-unisa/KGSum/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/isislab-unisa/KGSum.svg?style=for-the-badge
[forks-url]: https://github.com/isislab-unisa/KGSum/network/members
[stars-shield]: https://img.shields.io/github/stars/mariocosenza/kgsum.svg?style=for-the-badge
[stars-url]:https://github.com/isislab-unisa/KGSum/stargazers
[issues-shield]: https://img.shields.io/github/issues/isislab-unisa/KGSum.svg?style=for-the-badge
[issues-url]: https://github.com/isislab-unisa/KGSum/issues
[license-shield]: https://img.shields.io/github/license/isislab-unisa/KGSum.svg?style=for-the-badge
[license-url]: https://github.com/isislab-unisa/KGSum/blob/master/LICENSE.txt
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://it.linkedin.com/school/isislabunisa/

[product-screenshot]: images/DemoKgSum.gif
