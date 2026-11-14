# MTEB retrieval public model cache

The pinned task instruction requires `mteb==1.36.8` and `BAAI/bge-small-zh-v1.5` at revision `7999e1d3359715c523056ef9478215996d62a620`. The task image already includes MTEB, CPU PyTorch and Transformers. Preparation downloads the model weights, tokenizer and sentence-transformer configuration from that exact public revision, then disables internet access and encodes one synthetic dependency-probe sentence through `mteb.get_model`.

The model file list is verified against the [public revision](https://huggingface.co/BAAI/bge-small-zh-v1.5/tree/7999e1d3359715c523056ef9478215996d62a620), including `1_Pooling/config.json`. The cache contains no task answer, official test file, ranking result or encoded task corpus. Both network arms receive identical hashed bytes. Native empty and oracle controls must execute the official assertions before model evaluation is released.
