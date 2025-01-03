from fastapi import FastAPI, File, Form, UploadFile
import asyncio
from io import BytesIO
from PIL import Image
import numpy as np
import random
import logging
from fastapi.middleware.cors import CORSMiddleware
import base64
from fastapi.responses import JSONResponse
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Replace with your React app's URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def split_image(image, grid_size=10):
    width, height = image.size
    piece_width, piece_height = width // grid_size, height // grid_size
    image = image.resize((piece_width * grid_size, piece_height * grid_size))
    pieces, original_sequence = [], []
    for i in range(grid_size):
        for j in range(grid_size):
            box = (j * piece_width, i * piece_height, (j + 1) * piece_width, (i + 1) * piece_height)
            pieces.append(image.crop(box))
            original_sequence.append(i * grid_size + j)
    return pieces, original_sequence

def create_chromosome(pieces):
    chromosome = list(range(len(pieces)))
    random.shuffle(chromosome)
    return chromosome

def compare_edges(piece1, piece2, direction):


    arr1, arr2 = np.array(piece1).astype(np.int16), np.array(piece2).astype(np.int16)
    edge1, edge2 = (arr1[:, -1, :], arr2[:, 0, :]) if direction == 'right' else (arr1[-1, :, :], arr2[0, :, :])
    return 1 - (np.mean(np.abs(edge1 - edge2)) / 255)

def calculate_fitness(chromosome, pieces, original_sequence, grid_size=10):
    fitness = 0
    correct_positions = [chromosome[i] == original_sequence[i] for i in range(len(chromosome))]
    for i in range(grid_size):
        for j in range(grid_size):
            index = i * grid_size + j
            if j < grid_size - 1:
                fitness += compare_edges(pieces[chromosome[index]], pieces[chromosome[i * grid_size + (j + 1)]], 'right')
            if i < grid_size - 1:
                fitness += compare_edges(pieces[chromosome[index]], pieces[chromosome[(i + 1) * grid_size + j]], 'bottom')

    return fitness + sum(correct_positions) * 5, correct_positions

def tournament_selection(population, fitnesses, k=3):
    return max(random.sample(list(zip(population, fitnesses)), k), key=lambda x: x[1])[0]

def crossover(parent1, parent2):
    size = len(parent1)
    start, end = sorted(random.sample(range(size), 2))
    child = [None] * size
    child[start:end+1] = parent1[start:end+1]
    p2_index = 0
    for i in range(size):
        if child[i] is None:
            while parent2[p2_index] in child:
                p2_index += 1
            child[i] = parent2[p2_index]
            p2_index += 1
    return child

def mutate(chromosome, mutation_rate=0.05):
    for i in range(len(chromosome)):
        if random.random() < mutation_rate:
            j = random.randint(0, len(chromosome) - 1)
            chromosome[i], chromosome[j] = chromosome[j], chromosome[i]
    return chromosome

def genetic_algorithm(pieces, original_sequence, population_size=100, generations=100, mutation_rate=0.05, grid_size=10, elite_count=10, stagnation_threshold=20):
    population = [create_chromosome(pieces) for _ in range(population_size)]
    print("Population", population)
    best_solutions, global_best_chromo, global_best_fitness, stagnation_counter = [], None, float('-inf'), 0

    for generation in range(generations):
        fitness_results = [calculate_fitness(chromo, pieces, original_sequence, grid_size) for chromo in population]

        fitnesses = [result[0] for result in fitness_results]
        correct_counts = [sum(result[1]) for result in fitness_results]
        best_index = np.argmax(fitnesses)
        if fitnesses[best_index] > global_best_fitness:
            global_best_chromo, global_best_fitness = population[best_index].copy(), fitnesses[best_index]
            stagnation_counter = 0
        else:
            stagnation_counter += 1

        best_solutions.append((global_best_chromo.copy(), global_best_fitness, correct_counts[best_index]))

        if stagnation_counter >= stagnation_threshold:
            for i in range(int(population_size * 0.5)):
                population[-(i + 1)] = create_chromosome(pieces)
            stagnation_counter = 0

        sorted_population = [chromosome for _, chromosome in sorted(zip(fitnesses, population), key=lambda x: x[0], reverse=True)]
        new_population = [chromosome.copy() for chromosome in sorted_population[:elite_count]]

        while len(new_population) < population_size:
            parent1, parent2 = tournament_selection(population, fitnesses), tournament_selection(population, fitnesses)
            child = mutate(crossover(parent1, parent2), mutation_rate)
            new_population.append(child)
        new_population[0] = global_best_chromo.copy()
        population = new_population
    return best_solutions

def assemble_image(chromosome, pieces, grid_size=10):
    piece_width, piece_height = pieces[0].size
    assembled_image = Image.new('RGB', (piece_width * grid_size, piece_height * grid_size))
    for i in range(grid_size):
        for j in range(grid_size):
            assembled_image.paste(pieces[chromosome[i * grid_size + j]], (j * piece_width, i * piece_height))
    return assembled_image


@app.post("/solve")
async def solve_puzzle(
        image: UploadFile = File(...),
        grid_size: int = Form(...),
        population_size: int = Form(...),
        generations: int = Form(...),
        mutation_rate: float = Form(...)
):
    logger.info("Request received for solving the puzzle.")
    image_data = await image.read()
    logger.info("Image data received and being processed.")
    img = Image.open(BytesIO(image_data))
    pieces, original_sequence = split_image(img, grid_size)
    logger.info(f"Image split into {len(pieces)} pieces.")

    best_solutions = genetic_algorithm(
        pieces, original_sequence, population_size, generations, mutation_rate, grid_size
    )
    print("Best solutions", best_solutions)


    generation_images = []
    for index, (chromosome, fitness, correct_positions) in enumerate(best_solutions):
        solved_image = assemble_image(chromosome, pieces, grid_size)
        buffer = BytesIO()
        solved_image.save(buffer, format="PNG")
        encoded_image = base64.b64encode(buffer.getvalue()).decode("utf-8")
        generation_images.append({
            "generation": index,
            "fitness": fitness,
            "correct_positions": correct_positions,
            "image": encoded_image,
        })

    return JSONResponse(content=generation_images)


if __name__ == "__main__":
    import uvicorn
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    uvicorn.run(app, host="0.0.0.0", port=8000)
