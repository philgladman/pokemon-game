import * as THREE from "three";

import type { AppearanceDefinition, PrimitiveAsset } from "./types";

export type GltfSceneLoader = (url: string) => Promise<THREE.Object3D>;

async function loadGltfScene(url: string): Promise<THREE.Object3D> {
  const { GLTFLoader } = await import("three/addons/loaders/GLTFLoader.js");
  return (await new GLTFLoader().loadAsync(url)).scene;
}

export function requireAppearance(
  manifest: Record<string, AppearanceDefinition>,
  id: string,
): AppearanceDefinition {
  const appearance = manifest[id];
  if (appearance === undefined) {
    throw new Error(`Unknown appearance ${id}`);
  }
  return appearance;
}

export class AssetFactory {
  constructor(private readonly loadGltf: GltfSceneLoader = loadGltfScene) {}

  create(appearance: AppearanceDefinition): THREE.Group {
    const root = new THREE.Group();
    if (appearance.base_color !== null) {
      root.add(this.makeBase(appearance.base_color));
    }

    const sourceGroup = new THREE.Group();
    root.add(sourceGroup);
    if (appearance.source.type === "primitive") {
      sourceGroup.add(this.makePrimitive(appearance.source));
      return root;
    }

    const fallback = this.makePrimitive(appearance.source.fallback);
    sourceGroup.add(fallback);
    const gltfSource = appearance.source;
    void this.loadGltf(gltfSource.url)
      .then((scene) => {
        if (root.userData.disposed === true) {
          this.dispose(scene);
          return;
        }
        sourceGroup.remove(fallback);
        this.dispose(fallback);
        scene.scale.set(...gltfSource.scale);
        this.configureShadows(scene);
        sourceGroup.add(scene);
      })
      .catch((error: unknown) => {
        console.warn(`Unable to load ${gltfSource.url}; using primitive fallback.`, error);
      });
    return root;
  }

  dispose(object: THREE.Object3D): void {
    object.userData.disposed = true;
    object.traverse((child) => {
      if (!(child instanceof THREE.Mesh)) {
        return;
      }
      child.geometry.dispose();
      const materials = Array.isArray(child.material) ? child.material : [child.material];
      materials.forEach((material) => material.dispose());
    });
  }

  private makeBase(color: string): THREE.Mesh {
    const base = new THREE.Mesh(
      new THREE.BoxGeometry(1, 0.08, 1),
      new THREE.MeshStandardMaterial({ color, roughness: 0.9 }),
    );
    base.position.y = -0.04;
    base.receiveShadow = true;
    return base;
  }

  private makePrimitive(asset: PrimitiveAsset): THREE.Object3D {
    if (asset.shape === "tree") {
      return this.makeTree(asset);
    }

    const geometry =
      asset.shape === "capsule"
        ? new THREE.CapsuleGeometry(0.25, 0.42, 5, 10)
        : new THREE.BoxGeometry(1, asset.shape === "flat" ? 0.08 : 1, 1);
    const object = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({ color: asset.color, roughness: 0.82 }),
    );
    object.scale.set(...asset.scale);
    if (asset.shape === "flat") {
      object.position.y = -0.04;
    } else if (asset.shape === "box") {
      object.position.y = asset.scale[1] / 2;
    }
    object.castShadow = asset.shape !== "flat";
    object.receiveShadow = true;
    return object;
  }

  private makeTree(asset: PrimitiveAsset): THREE.Group {
    const tree = new THREE.Group();
    tree.scale.set(...asset.scale);
    const trunk = new THREE.Mesh(
      new THREE.CylinderGeometry(0.12, 0.16, 0.65, 8),
      new THREE.MeshStandardMaterial({ color: asset.secondary_color ?? "#76513a" }),
    );
    trunk.position.y = 0.32;
    trunk.castShadow = true;
    tree.add(trunk);
    const crown = new THREE.Mesh(
      new THREE.ConeGeometry(0.48, 1.05, 8),
      new THREE.MeshStandardMaterial({ color: asset.color }),
    );
    crown.position.y = 1.05;
    crown.castShadow = true;
    tree.add(crown);
    return tree;
  }

  private configureShadows(object: THREE.Object3D): void {
    object.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        child.castShadow = true;
        child.receiveShadow = true;
      }
    });
  }
}
