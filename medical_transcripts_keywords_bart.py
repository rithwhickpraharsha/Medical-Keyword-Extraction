# -*- coding: utf-8 -*-
"""medical-transcripts-keywords-bart.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1oSua497Rb8lqd6jSXN_y-AgcnfGTL_C9

### Importing Libraries
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import torch
from torch.optim import Adam
from torch.utils.data import Dataset, DataLoader

# from google.colab import drive
# drive.mount('/content/drive')

"""### Loading and preparing the Dataset"""

import pandas as pd
df_medical = pd.read_csv("https://raw.githubusercontent.com/Saloni-glit/Medical-dataset/main/mtsamples.csv")
df_medical.head()

df_medical.shape

"""### Using Transcription column and keywords column"""

df_medical = df_medical.loc[:,["transcription", "keywords"]]
df_medical

"""### Let us look at the nulls in the DataFrame"""

df_medical.isnull().sum()

"""### Removing Null values from the data"""

df_medical = df_medical[~(df_medical['transcription'].isnull()) &
                        ~(df_medical['keywords'].isnull()) ]

df_medical.shape

"""### Let us see the length of input and output"""

transcription = df_medical['transcription'].apply(lambda x: len(x.split()))
sns.distplot(transcription)

"""##### Fixing Input Length to 750 tokens with Padding and truncation"""

keywords = df_medical['keywords'].apply(lambda x: len(x.split()))

sns.distplot(keywords)

"""### Let us use at most 100 keywords"""

np.quantile(transcription,0.95)

df_medical

"""!pip install accelerate bitsandbytes

This command installs the accelerate and bitsandbytes libraries. These libraries are used for efficient distributed training and mixed-precision training, respectively.

Then we load the BART model for conditional generation from the Hugging Face model hub. The tokenizer is configured with padding on the left and truncation on the right.  the model is loaded onto the GPU.
"""

!pip install accelerate bitsandbytes
from transformers import BartForConditionalGeneration, AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("facebook/bart-base", padding_side="left",
                                         truncation_side='right')

if torch.cuda.is_available():
    model = BartForConditionalGeneration.from_pretrained("facebook/bart-base").to("cuda")
                                                     # load_in_8bit=True)
else:
    model = BartForConditionalGeneration.from_pretrained("facebook/bart-base")

"""### For a pytorch model we need a DataLoader so implementing a Dataloader

The `MedicalKeywordDataset` class is a PyTorch dataset designed for handling medical text data with associated keywords. It facilitates the creation of training and testing datasets for machine learning tasks, specifically for keyword extraction.

## Class Initialization

### Parameters:
- `df`: Pandas DataFrame containing the medical data.
- `transcript`: Column name representing the medical transcriptions.
- `keywords`: Column name representing the associated keywords.
- `tokenizer`: Tokenizer for encoding text data.
- `in_len`: Maximum length of the input transcriptions.
- `out_len`: Maximum length of the output keywords.

transcript_tokens: Tensor containing encoded transcript tokens.             
keyword_tokens: Tensor containing encoded keyword tokens.

batch_size: Number of samples in each batch.       
shuffle: If True, the dataset will be shuffled during each epoch.

"""

class MedicalKeywordDataset(Dataset):
    def __init__(self, df, transcript, keywords, tokenizer, in_len, out_len):
        self.df = df
        self.transcript = transcript
        self.keywords = keywords
        self.tokenizer = tokenizer
        self.in_len = in_len
        self.out_len = out_len

    def __len__(self):
        return self.df.shape[0]

    def __getitem__(self, idx):
        #print(self.df[self.transcript].iloc[idx])
        transcript_tokens = self.tokenizer(self.df[self.transcript].iloc[idx],
                                          padding='max_length',
                                          truncation=True,
                                          max_length=self.in_len,
                                          return_tensors='pt'
                                          )['input_ids']

        keyword_tokens = self.tokenizer(self.df[self.keywords].iloc[idx],
                                       padding="max_length", truncation=True,
                                       max_length=self.out_len,
                                       return_tensors='pt')['input_ids']

        ### Moving the tensors to GPU
        if torch.cuda.is_available():
            transcript_tokens = transcript_tokens.to("cuda")
            keyword_tokens = keyword_tokens.to("cuda")
        #print(transcript_tokens)
        return transcript_tokens[0,:], keyword_tokens[0,:]




from sklearn.model_selection import train_test_split

### Splitting the data to train and test sets
df_train, df_test = train_test_split(df_medical, train_size=0.9, random_state=34)


ds_train = MedicalKeywordDataset(df_train,'transcription','keywords',tokenizer,
                            750, 100)

ds_test = MedicalKeywordDataset(df_test,'transcription','keywords',tokenizer,
                            750, 100)


### Converting dataset object to dataloader object
batch_size = 6

### Conversion
dl_train = DataLoader(ds_train, batch_size=batch_size, shuffle=True)
dl_test = DataLoader(ds_test, batch_size=batch_size, shuffle=True)

"""### Now let us write the train and validation functions

### Optimizer Initialization

The Adam optimizer is used for training the model. It is initialized with a learning rate of 2e-4.



"""

### Optimizer Adam used here
optimizer = Adam(model.parameters(),lr=2e-4)

### Defining Epochs
epochs = 3

def num_batches(total, batch_size):
    if total % batch_size == 0:
        return total // batch_size
    else:
        return total // batch_size + 1


### Number of batches defined for a dataset
train_batches = num_batches(df_train.shape[0],batch_size)
test_batches = num_batches(df_test.shape[0],batch_size)


### Function to train model
def train(data,num_batches, model, optimizer):
    model.train()
    model_loss = 0
    model_acc = 0
    i = 0
    for tr, kw in data:
        optimizer.zero_grad()
        #print(kw.shape)
        ### Feed forward Pass
        out = model(tr, labels=kw)

        ### Loss computation
        r_loss = out.loss
        model_loss += r_loss.item()

        ### Accuracy Computation
        logits = out.logits
        preds = torch.softmax(logits,dim=2)
        preds = torch.argmax(preds,dim=2)
        acc = torch.sum(kw == preds).item()/(kw.shape[0]*kw.shape[1])
        model_acc += acc

        ### Backpropogation
        r_loss.backward()
        optimizer.step()

        i+=1
        print("[" + "="*(50*i//num_batches) + ">" +
              " "*(50*(1 - i//num_batches))
              + "]" + f"loss={model_loss/i} accuracy={model_acc/i}",
              end="\r")

    print("[" + "="*(50*i//num_batches) + ">" +
              " "*(50*(1 - i//num_batches))
              + "]" + f"loss={model_loss/i} accuracy={model_acc/i}",
              end="\n")


def test(data,num_batches, model):
    model.eval()
    model_loss = 0
    model_acc = 0
    i = 0
    for tr, kw in data:
        #optimzer.zero_grad()

        ### Feed forward Pass
        out = model(tr, labels=kw)

        ### Loss computation
        r_loss = out.loss
        model_loss += r_loss.item()

        ### Accuracy Computation
        logits = out.logits
        preds = torch.softmax(logits,dim=2)
        preds = torch.argmax(preds,dim=2)
        acc = torch.sum(kw == preds).item()/(kw.shape[0]*kw.shape[1])
        model_acc += acc

#         ### No Backpropogation as it is evaluation of model
#         r_loss.backward()
#         optimizer.step()

        i+=1
        print("[" + "="*(50*i//num_batches) + ">" +
              " "*(50*(1 - i//num_batches))
              + "]" + f"loss={model_loss/i} accuracy={model_acc/i}",
              end="\r")

    print("[" + "="*(50*i//num_batches) + ">" +
              " "*(50*(1 - i//num_batches))
              + "]" + f"loss={model_loss/i} accuracy={model_acc/i}",
              end="\n")

"""#LOSS AND ACCURACY FOR 6 BATCHES"""

for e in range(epochs):
    train(dl_train,train_batches,model, optimizer)
    test(dl_test, test_batches,model)

df_medical

"""### Let us compare the predictions from the test data

The generate_keywords function is designed to generate keywords for transcriptions using a pre-trained language model. Below is the detailed documentation for the function:

Input Parameters:
df: Pandas DataFrame containing the transcriptions.
transcription: Name of the column in the DataFrame containing the transcriptions.
model: Pre-trained language model capable of keyword generation.
tokenizer: Tokenizer used to tokenize the input transcriptions.
Output:
The function returns a modified DataFrame (df) with an additional column named 'Result' containing the generated keywords.

Tokenization and Preprocessing:

Tokenizes the transcriptions using the provided tokenizer.
Converts the input transcriptions to PyTorch tensors.
Optionally moves the tensors to the GPU if available.

Model Inference and Decoding:

Uses the pre-trained language model to generate keywords.
Specifies the minimum and maximum length constraints for the generated keywords.

Decoding and Post-processing:

Decodes the generated token IDs into human-readable keywords using the tokenizer.
Removes special tokens from the decoded keywords.
"""

def generate_keywords(df,transcription, model, tokenizer):
    df['Result'] = df[transcription].apply(lambda x: tokenizer(x, max_length=750,
    padding='max_length', truncation=True, return_tensors='pt')['input_ids'])
    if torch.cuda.is_available():
        df['Result'] = df['Result'].apply(lambda x: x.to("cuda"))

    df['Result'] = df['Result'].apply(lambda x: model.generate(x,
                                                    min_length=20,
                                                    max_length=100 ))
    df['Result'] = df['Result'].apply(lambda x: tokenizer.batch_decode(x,
                                                    skip_special_tokens=True))
    return df

df_res = generate_keywords(df_test,'transcription',model,tokenizer)

"""The model.generate method is used to generate sequences of tokens from a given input sequence using a pre-trained language model. Below is the detailed documentation for the method:

Input Parameters:
input_ids: PyTorch tensor representing the input sequence. It contains token IDs.
max_length: Maximum length of the generated sequence. If specified, it constrains the maximum number of tokens in the output sequence.

Output:
The method returns a PyTorch tensor containing the generated token IDs for the sequence.
"""

model.generate(tokenizer(df_test['transcription'].iloc[0],max_length=750,
                        padding="max_length", truncation=True,
                        return_tensors='pt')['input_ids'].to('cuda'),max_length=100)

"""###Documentation for tokenizer Method
The tokenizer method is used to tokenize a text sequence using a pre-trained tokenizer. Below is the detailed documentation for the method:

Input Parameters:
text: Input text sequence that needs to be tokenized.

max_length : Maximum length of the tokenized sequence. If specified, it constrains the maximum number of tokens in the output sequence.
padding : Specifies the padding strategy. If specified, it pads the sequences to the maximum length.
truncation : Specifies whether to truncate the sequences to the maximum length if they exceed it.

Output:
The method returns a dictionary containing tokenized information, including:

input_ids: Token IDs representing the input sequence.
attention_mask: Attention mask indicating which tokens should be attended to.
"""

tokenizer(df_test['transcription'].iloc[0],max_length=750,
                        padding="max_length", truncation=True)

df_res['Result'] = df_res['Result'].apply(lambda x: x[0])

"""# RESULTS"""

print(df_res['keywords'].iloc[0])
print(df_res['Result'].iloc[0])

df_res

"""### Looking at top 5"""

for i in range(5):

    print(f"-----------------Row no {i+1}------------------")
    print("Transcription:")
    print(df_res['transcription'].iloc[i])
    print("\n")
    print("Keywords:")
    print(df_res['keywords'].iloc[i])
    print("\n")
    print("Result:")
    print(df_res['Result'].iloc[i])
    print("\n"*3)

