from fastapi import FastAPI

app=FastAPI()


@app.get("/")

# Read the root endpoint
def read_root():
    return {"Hello": "World"}
